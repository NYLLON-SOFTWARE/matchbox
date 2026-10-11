use axum::body::{Body, to_bytes};
use axum::http::{Request, Response};
use tower::ServiceExt;

use super::*;
use crate::app::{Booted, boot};
use crate::config::Config;

const TOKEN: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const OTHER_TOKEN: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

async fn app(token: &str) -> (Booted, tempfile::TempDir) {
    let dir = tempfile::tempdir().unwrap();
    let config = Config::from_lookup(|name| match name {
        "SECRET_KEY_BASE" => Some("setup-access-test-secret".repeat(4)),
        "DISABLE_SSL" => Some("1".into()),
        "EMBER_SETUP_TOKEN" => Some(token.into()),
        "EMBER_STORAGE_PATH" => Some(dir.path().to_string_lossy().into_owned()),
        _ => None,
    })
    .unwrap();
    (boot(config).await.unwrap(), dir)
}

fn request(method: &str, path: &str, body: &str, cookie: Option<&str>) -> Request<Body> {
    let mut request = Request::builder()
        .method(method)
        .uri(path)
        .header("host", "campfire.test")
        .header("x-forwarded-proto", "https")
        .header("origin", "https://campfire.test")
        .header("sec-fetch-site", "same-origin")
        .header("content-type", "application/x-www-form-urlencoded");
    if let Some(cookie) = cookie {
        request = request.header("cookie", cookie);
    }
    request.body(Body::from(body.to_string())).unwrap()
}

async fn send(app: &Booted, request: Request<Body>) -> Response<Body> {
    app.router.clone().oneshot(request).await.unwrap()
}

fn assert_private(response: &Response<Body>) {
    assert_referrer_policy(response, "no-referrer");
}

fn assert_referrer_policy(response: &Response<Body>, policy: &str) {
    assert_eq!(response.headers()["cache-control"], "no-store");
    assert_eq!(response.headers()["referrer-policy"], policy);
}

async fn unlock(app: &Booted) -> String {
    let response = send(app, request("POST", "/first_run/access", &format!("token={TOKEN}"), None)).await;
    assert_eq!(response.status(), StatusCode::NO_CONTENT);
    assert_private(&response);
    let cookie = response.headers()["set-cookie"].to_str().unwrap();
    for attribute in ["path=/", "secure", "httponly", "samesite=strict", "expires="] {
        assert!(cookie.to_ascii_lowercase().contains(attribute), "{cookie}");
    }
    assert!(!cookie.to_ascii_lowercase().contains("domain="));
    assert!(!cookie.contains(TOKEN));
    cookie.split(';').next().unwrap().to_string()
}

#[tokio::test]
async fn locked_setup_cannot_create_an_account_or_stage_files() {
    let (app, dir) = app(TOKEN).await;
    for (method, body) in [("GET", ""), ("POST", "user[name]=Ada&user[email_address]=ada%40example.test&user[password]=password123")] {
        let response = send(&app, request(method, "/first_run", body, None)).await;
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
        assert_private(&response);
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert!(!String::from_utf8_lossy(&body).contains(TOKEN));
    }
    let accounts = app.app.db.read(ember_db::Account::count).await.unwrap();
    assert_eq!(accounts, 0);
    assert_eq!(std::fs::read_dir(dir.path().join("files")).unwrap().count(), 0);
}

#[tokio::test]
async fn exchange_requires_https_same_origin_and_body_token() {
    let (app, _dir) = app(TOKEN).await;
    for (method, path, body, status) in [
        ("GET", "/first_run/access?token=secret", "", StatusCode::BAD_REQUEST),
        ("POST", "/first_run/access?token=secret", "token=wrong", StatusCode::BAD_REQUEST),
        ("POST", "/first_run/access", "token=wrong", StatusCode::FORBIDDEN),
        ("POST", "/first_run/access", "", StatusCode::FORBIDDEN),
        ("POST", "/first_run/access", "token[]=bad", StatusCode::FORBIDDEN),
    ] {
        let response = send(&app, request(method, path, body, None)).await;
        assert_eq!(response.status(), status, "{method} {path}");
        assert_private(&response);
        assert!(response.headers().get("set-cookie").is_none());
    }
    for (site, origin) in
        [("cross-site", "https://attacker.test"), ("same-site", "https://campfire.test"), ("same-origin", "https://attacker.test")]
    {
        let mut request = request("POST", "/first_run/access", &format!("token={TOKEN}"), None);
        request.headers_mut().insert("sec-fetch-site", site.parse().unwrap());
        request.headers_mut().insert("origin", origin.parse().unwrap());
        let response = send(&app, request).await;
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
        assert_private(&response);
        assert!(response.headers().get("set-cookie").is_none());
    }
    let mut insecure = request("POST", "/first_run/access", &format!("token={TOKEN}"), None);
    insecure.headers_mut().remove("x-forwarded-proto");
    insecure.headers_mut().insert("origin", "http://campfire.test".parse().unwrap());
    let response = send(&app, insecure).await;
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    assert_private(&response);
    assert!(response.headers().get("set-cookie").is_none());

    let mut malformed = request("POST", "/first_run/access", "token=one&token[]=two", None);
    malformed.headers_mut().remove("sec-fetch-site");
    let response = send(&app, malformed).await;
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    assert_private(&response);
}

#[tokio::test]
async fn unlock_cookie_is_short_lived_bound_to_the_current_token_and_not_a_raw_bearer() {
    let (app, _dir) = app(TOKEN).await;
    let cookie = unlock(&app).await;
    let response = send(&app, request("GET", "/first_run", "", Some(&cookie))).await;
    assert_eq!(response.status(), StatusCode::OK);
    assert_referrer_policy(&response, "same-origin");
    let response = send(&app, request("GET", "/first_run/access", "", None)).await;
    assert_eq!(response.status(), StatusCode::OK);
    assert_private(&response);
    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let body = String::from_utf8_lossy(&body);
    assert!(body.contains(&ember_assets::asset_path("setup_access.js")));
    assert!(!body.contains(TOKEN));

    let setup = app.app.config.setup_token.as_ref().unwrap();
    let expired = rails_compat::cookies::encrypt(
        &app.app.secrets,
        COOKIE_NAME,
        &json!(setup.fingerprint()),
        Some(app.app.clock.now() - SignedDuration::from_secs(1)),
    );
    let expired = format!("{COOKIE_NAME}={}", rails_compat::cookies::escape(&expired));
    for invalid in [expired, format!("{COOKIE_NAME}={TOKEN}"), format!("{cookie}tampered")] {
        let response = send(&app, request("GET", "/first_run", "", Some(&invalid))).await;
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
        assert_private(&response);
    }
    let (rotated, _other_dir) = self::app(OTHER_TOKEN).await;
    let response = send(&rotated, request("GET", "/first_run", "", Some(&cookie))).await;
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn completed_setup_invalidates_access_and_clears_the_host_cookie() {
    let (app, _dir) = app(TOKEN).await;
    let cookie = unlock(&app).await;
    let response = send(
        &app,
        request("POST", "/first_run", "user[name]=Ada&user[email_address]=ada%40example.test&user[password]=password123", Some(&cookie)),
    )
    .await;
    assert_eq!(response.status(), StatusCode::FOUND);
    assert_private(&response);
    let expired = response
        .headers()
        .get_all("set-cookie")
        .iter()
        .map(|value| value.to_str().unwrap())
        .find(|value| value.starts_with(COOKIE_NAME))
        .unwrap();
    assert!(expired.to_ascii_lowercase().contains("secure"));
    assert!(expired.to_ascii_lowercase().contains("httponly"));
    assert!(expired.contains("1970"));
    for (method, path, body) in
        [("GET", "/first_run", ""), ("GET", "/first_run/access", ""), ("POST", "/first_run/access", &format!("token={TOKEN}"))]
    {
        let response = send(&app, request(method, path, body, Some(&cookie))).await;
        assert_eq!(response.status(), StatusCode::FOUND);
        assert!(response.headers()["location"].to_str().unwrap().ends_with('/'));
        assert_private(&response);
        let expired = response.headers()["set-cookie"].to_str().unwrap();
        assert!(expired.starts_with(COOKIE_NAME));
        assert!(expired.contains("1970"));
    }
    assert_eq!(app.app.db.read(ember_db::Account::count).await.unwrap(), 1);
}

#[tokio::test]
async fn authorized_native_setup_validation_preserves_the_form_and_same_origin_policy() {
    let (app, _dir) = app(TOKEN).await;
    let cookie = unlock(&app).await;
    let mut native =
        request("POST", "/first_run", "user[name]=Ada&user[email_address]=ada%40example.test&user[password]=short", Some(&cookie));
    native.headers_mut().insert("accept", "text/html,application/xhtml+xml".parse().unwrap());
    native.headers_mut().insert("sec-fetch-mode", "navigate".parse().unwrap());
    native.headers_mut().insert("sec-fetch-dest", "document".parse().unwrap());
    let response = send(&app, native).await;
    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_referrer_policy(&response, "same-origin");
    let html = String::from_utf8(to_bytes(response.into_body(), usize::MAX).await.unwrap().to_vec()).unwrap();
    assert!(html.contains("aria-invalid=\"true\""));
    assert!(html.contains("value=\"Ada\""));
    assert!(html.contains("value=\"ada@example.test\""));
    let password = html.split('<').find(|tag| tag.starts_with("input ") && tag.contains("id=\"user_password\"")).unwrap();
    assert!(!password.contains("value="));
    assert!(!html.contains(TOKEN));
    assert_eq!(app.app.db.read(ember_db::Account::count).await.unwrap(), 0);
}

#[tokio::test]
async fn setup_form_csrf_and_parser_errors_never_opt_into_same_origin_referrers() {
    let (app, _dir) = app(TOKEN).await;
    let cookie = unlock(&app).await;
    let body = "user[name]=Ada&user[email_address]=ada%40example.test&user[password]=short";
    for (origin, site) in [
        ("null", Some("same-origin")),
        ("https://attacker.test", Some("same-origin")),
        ("https://campfire.test", Some("cross-site")),
        ("https://campfire.test", None),
    ] {
        let mut forged = request("POST", "/first_run", body, Some(&cookie));
        forged.headers_mut().insert("origin", origin.parse().unwrap());
        match site {
            Some(site) => {
                forged.headers_mut().insert("sec-fetch-site", site.parse().unwrap());
            }
            None => {
                forged.headers_mut().remove("sec-fetch-site");
            }
        }
        forged.headers_mut().insert("referrer-policy", "same-origin".parse().unwrap());
        let response = send(&app, forged).await;
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
        assert_private(&response);
        let html = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert!(!String::from_utf8_lossy(&html).contains("id=\"user_password\""));
    }
    for (method, path, body, status) in [
        ("GET", "/first_run?token=secret", "", StatusCode::BAD_REQUEST),
        ("POST", "/first_run?token=secret", body, StatusCode::BAD_REQUEST),
        ("POST", "/first_run", "user=one&user[]=two", StatusCode::BAD_REQUEST),
        ("GET", "/first_run.json", "", StatusCode::NOT_ACCEPTABLE),
    ] {
        let response = send(&app, request(method, path, body, Some(&cookie))).await;
        assert_eq!(response.status(), status, "{method} {path}");
        assert_private(&response);
    }
    assert_eq!(app.app.db.read(ember_db::Account::count).await.unwrap(), 0);
}
