//! Installer-owned first-run authorization. The token stays in the link's fragment and is
//! exchanged over HTTPS for a short-lived encrypted cookie before the ordinary form is shown.

use ember_kit::{Cookie, Ctx, Error, Result, SameSite, StatusCode, halt};
use jiff::{SignedDuration, Timestamp};
use serde_json::json;

use crate::app::AppCtx;
use crate::concerns::{self, Before};

const COOKIE_NAME: &str = "__Host-ember_setup";
const COOKIE_LIFETIME: SignedDuration = SignedDuration::from_mins(15);
const LOCKED: &str = "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Ember setup</title><h1>Setup is locked</h1><p>Open the private setup link printed by the installer.</p></html>";

pub async fn show(c: &mut Ctx) -> Result {
    let result = show_access(c).await;
    finish_private(c, result)
}

async fn show_access(c: &mut Ctx) -> Result {
    concerns::before_actions(c, Before::default().allow_unauthenticated_access()).await?;
    reject_query(c)?;
    super::prevent_repeats(c).await?;
    if c.app().config.setup_token.is_none() {
        return Err(Error::NotFound);
    }
    require_https(c)?;
    let script = ember_assets::asset_path("setup_access.js");
    Ok(c.render_html(StatusCode::OK, format!(
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Ember setup</title><h1>Ember setup</h1><p id=\"status\" role=\"status\">Opening your private setup link…</p><noscript>Enable JavaScript to open this private setup link.</noscript><script type=\"module\" src=\"{script}\"></script></html>"
    )).header("content-security-policy", "default-src 'none'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'").header("x-frame-options", "DENY"))
}

pub async fn create(c: &mut Ctx) -> Result {
    let result = exchange(c).await;
    finish_private(c, result)
}

async fn exchange(c: &mut Ctx) -> Result {
    concerns::before_actions(c, Before::default().allow_unauthenticated_access()).await?;
    reject_query(c)?;
    super::prevent_repeats(c).await?;
    let Some(setup) = c.app().config.setup_token.as_ref() else { return Err(Error::NotFound) };
    require_https(c)?;
    // Header-based CSRF remains enabled above. Unlocking additionally requires an exact-origin
    // fetch, never the same-site allowance used by inherited forms.
    if c.request.header("sec-fetch-site") != Some("same-origin") || c.request.origin() != Some(c.request.base_url().as_str()) {
        return Err(Error::InvalidCrossOriginRequest);
    }
    if c.request.content_type().and_then(|value| value.split(';').next()) != Some("application/x-www-form-urlencoded") {
        return Err(Error::Status(StatusCode::UNSUPPORTED_MEDIA_TYPE));
    }
    // Query parameters override bodies in Rails' merged params, so this deliberately reads only
    // the body and rejects all queries before checking the bearer token.
    let valid = c.request_params.str("token").is_some_and(|token| setup.matches(token));
    if !valid {
        return Ok(c.head(StatusCode::FORBIDDEN));
    }
    let value = json!(setup.fingerprint());
    let expires = c.now() + COOKIE_LIFETIME;
    c.cookies.set_encrypted(COOKIE_NAME, &value, cookie().expires(expires))?;
    Ok(c.head(StatusCode::NO_CONTENT))
}

pub(super) fn authorize(c: &mut Ctx) -> Result<()> {
    let Some(setup) = c.app().config.setup_token.as_ref() else { return Ok(()) };
    reject_query(c)?;
    require_https(c)?;
    let permitted = c
        .cookies
        .encrypted(COOKIE_NAME)
        .and_then(|value| value.as_str().map(str::to_string))
        .is_some_and(|fingerprint| setup.matches_fingerprint(&fingerprint));
    if !permitted {
        clear_cookie(c);
        return halt(c.render_html(StatusCode::FORBIDDEN, LOCKED));
    }
    Ok(())
}

fn require_https(c: &Ctx) -> Result<()> {
    if c.request.is_ssl() { Ok(()) } else { Err(Error::Status(StatusCode::FORBIDDEN)) }
}

fn reject_query(c: &Ctx) -> Result<()> {
    if c.request.query_string().is_empty() { Ok(()) } else { Err(Error::Status(StatusCode::BAD_REQUEST)) }
}

fn cookie() -> Cookie {
    Cookie::new("").secure().httponly().same_site(Some(SameSite::Strict))
}

pub(super) fn clear_cookie(c: &mut Ctx) {
    if c.cookies.get(COOKIE_NAME).is_some() {
        // CookieJar's general delete helper does not add Secure; __Host cookies require it even
        // when expiring, along with Path=/ and no Domain.
        c.cookies.set(COOKIE_NAME, cookie().expires(Timestamp::UNIX_EPOCH));
    }
}

pub(super) fn finish_form(c: &mut Ctx, result: Result) -> Result {
    if c.app().config.setup_token.is_none() {
        return result;
    }
    finish_private(c, result).map(|response| {
        if matches!(response.status, StatusCode::OK | StatusCode::UNPROCESSABLE_ENTITY) {
            // Native forms with no-referrer send Origin: null and fail CSRF checks. Only an
            // authorized, token-free form render may send its referrer to the same origin.
            response.header("referrer-policy", "same-origin")
        } else {
            response
        }
    })
}

fn finish_private(c: &mut Ctx, result: Result) -> Result {
    c.no_store();
    c.set_header("referrer-policy", "no-referrer");
    result
}

#[cfg(test)]
mod tests;
