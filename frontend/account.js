// Sign in, register, one-time codes and the authenticator step for officials.
header(null);
const params = new URLSearchParams(location.search);
const forms = ["signinForm", "registerForm", "otpForm", "otpAskForm", "mfaForm", "forgotForm", "resetForm", "changeForm"];
let otpIdentifier = "", mfaToken = "", tab = params.get("tab") === "register" ? "register" : "signin";

function show(name) {
  forms.forEach(f => $(f).classList.toggle("hidden", f !== name));
  const top = name === "signinForm" || name === "registerForm";
  $("tabs").classList.toggle("hidden", !top);
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.t === (name === "registerForm" ? "register" : "signin")));
  const titles = { signinForm: "Sign in to SkyClear", registerForm: "Create your pilot account", otpForm: "Check your phone", otpAskForm: "Sign in with a code", mfaForm: "One more step", forgotForm: "Reset your password", resetForm: "Choose a new password", changeForm: "Choose your own password" };
  $("title").textContent = titles[name];
  $("lead").classList.toggle("hidden", !top);
}
document.querySelectorAll("#tabs button").forEach(b => b.addEventListener("click", () => show(b.dataset.t === "register" ? "registerForm" : "signinForm")));
if (params.get("expired")) $("notice").innerHTML = '<div class="msg">Your session ended. Please sign in again.</div>';
show(tab === "register" ? "registerForm" : "signinForm");
{ const me = session(); if (me && !params.get("change")) $("notice").innerHTML = `<div class="msg">You are already signed in as ${esc(me.user.name)}, ${esc(me.user.role)}. <a href="${me.user.role === "official" ? "official.html" : "index.html"}">Continue</a> or sign out from the menu to use another account.</div>`; }

const fail = (id, e) => { $(id).innerHTML = `<div class="msg err" role="alert">${esc(e.message)}</div>`; };
function finish(t) {
  setSession(t);
  if (t.user.must_change_password) { show("changeForm"); return; }
  const next = params.get("next");
  location.href = next || (t.user.role === "official" ? "official.html" : "index.html");
}
const channelWord = CFG.otpChannel === "sms" ? "your mobile number" : "your email";
function showCode(data, text) {
  otpIdentifier = data.identifier || otpIdentifier;
  $("otpText").textContent = text;
  $("devCode").innerHTML = data.dev_code ? `<div class="devcode">Demo mode: your code is <b>${esc(data.dev_code)}</b><br><span class="small">In production this arrives by SMS.</span></div>` : "";
  $("otpCode").value = ""; $("otpMsg").innerHTML = "";
  show("otpForm"); $("otpCode").focus();
}

$("signinForm").addEventListener("submit", async e => {
  e.preventDefault(); $("signinMsg").innerHTML = "";
  try {
    const r = await api("/auth/login", { method: "POST", auth: false, body: { identifier: $("lId").value, password: $("lPass").value } });
    if (r.mfa_required || r.mfa_setup_required) return startMfa(r);
    finish(r);
  } catch (err) {
    if (err.message === "not_verified") {
      try { const o = await api("/auth/otp/request", { method: "POST", auth: false, body: { identifier: $("lId").value } }); return showCode({ ...o, identifier: $("lId").value }, "Your account is not confirmed yet. We sent you a code."); }
      catch (e2) { return fail("signinMsg", e2); }
    }
    fail("signinMsg", err);
  }
});

async function startMfa(r) {
  mfaToken = r.mfa_token; $("mfaCode").value = ""; $("mfaMsg").innerHTML = ""; $("mfaSetup").innerHTML = "";
  if (r.mfa_setup_required) {
    $("mfaText").textContent = "Officials use an authenticator app. Scan this code with Google Authenticator, Microsoft Authenticator or any similar app, then enter the 6-digit code it shows.";
    try {
      const s = await api("/auth/totp/setup", { method: "POST", auth: false, body: { mfa_token: mfaToken } });
      $("mfaSetup").innerHTML = `<div class="qrbox">${qrSvg(s.otpauth_uri)}</div><div class="help">Cannot scan? Enter this key in the app: <span class="mono">${esc(s.secret)}</span></div>`;
    } catch (e) { fail("mfaMsg", e); }
  } else $("mfaText").textContent = "Enter the 6-digit code from your authenticator app.";
  show("mfaForm"); $("mfaCode").focus();
}
$("mfaForm").addEventListener("submit", async e => {
  e.preventDefault();
  try { finish(await api("/auth/totp/verify", { method: "POST", auth: false, body: { mfa_token: mfaToken, code: $("mfaCode").value } })); }
  catch (err) { fail("mfaMsg", err); }
});

$("registerForm").addEventListener("submit", async e => {
  e.preventDefault(); $("registerMsg").innerHTML = "";
  try {
    const r = await api("/auth/register", { method: "POST", auth: false, body: { name: $("rName").value, email: $("rEmail").value, phone: $("rPhone").value, password: $("rPass").value } });
    showCode(r, "We sent a 6-digit code to " + r.sent_to + ". Enter it to finish creating your account.");
  } catch (err) { fail("registerMsg", err); }
});

$("otpForm").addEventListener("submit", async e => {
  e.preventDefault();
  try { finish(await api("/auth/otp/verify", { method: "POST", auth: false, body: { identifier: otpIdentifier, code: $("otpCode").value } })); }
  catch (err) { fail("otpMsg", err); }
});
$("resend").addEventListener("click", async () => {
  try { const o = await api("/auth/otp/request", { method: "POST", auth: false, body: { identifier: otpIdentifier } }); showCode({ ...o, identifier: otpIdentifier }, "If the account exists, we sent a new code to " + channelWord + "."); }
  catch (err) { fail("otpMsg", err); }
});
$("otpBack").addEventListener("click", () => show("signinForm"));

$("useOtp").addEventListener("click", () => { $("oId").value = $("lId").value; show("otpAskForm"); });
$("otpAskBack").addEventListener("click", () => show("signinForm"));
$("otpAskForm").addEventListener("submit", async e => {
  e.preventDefault();
  try {
    const o = await api("/auth/otp/request", { method: "POST", auth: false, body: { identifier: $("oId").value } });
    // Same screen whether or not the account exists, so nobody can use this form to find out who has an account.
    showCode({ ...o, identifier: $("oId").value }, "If a pilot account matches, we sent a 6-digit code to " + channelWord + ".");
  } catch (err) { fail("otpAskMsg", err); }
});


// Forgot password: ask for a code, then set a new password with it.
$("forgot").addEventListener("click", () => { $("fId").value = $("lId").value; show("forgotForm"); });
document.querySelectorAll("[data-back]").forEach(b => b.addEventListener("click", () => show("signinForm")));
let resetId = "";
$("forgotForm").addEventListener("submit", async e => {
  e.preventDefault(); resetId = $("fId").value;
  try {
    const o = await api("/auth/password/forgot", { method: "POST", auth: false, body: { identifier: resetId } });
    $("resetText").textContent = "If an account matches, we sent a 6-digit code to " + channelWord + ". Enter it and choose a new password.";
    $("resetDev").innerHTML = o.dev_code ? `<div class="devcode">Test mode: your code is <b>${esc(o.dev_code)}</b></div>` : "";
    $("resetCode").value = ""; $("resetPass").value = ""; $("resetMsg").innerHTML = "";
    show("resetForm"); $("resetCode").focus();
  } catch (err) { fail("forgotMsg", err); }
});
$("resetForm").addEventListener("submit", async e => {
  e.preventDefault();
  try {
    await api("/auth/password/reset", { method: "POST", auth: false, body: { identifier: resetId, code: $("resetCode").value, new_password: $("resetPass").value } });
    show("signinForm"); $("lId").value = resetId; $("lPass").value = "";
    $("signinMsg").innerHTML = '<div class="msg">Password changed. Sign in with the new one.</div>';
  } catch (err) { fail("resetMsg", err); }
});

// An invited official signs in with a temporary password and must choose their own.
$("changeForm").addEventListener("submit", async e => {
  e.preventDefault();
  try {
    const t = await api("/auth/password/change", { method: "POST", body: { current_password: $("curPass").value, new_password: $("newPass").value } });
    setSession(t); location.href = t.user.role === "official" ? "official.html" : "index.html";
  } catch (err) { fail("changeMsg", err); }
});
if (params.get("change") && session()) show("changeForm");

// Say where codes go, and hide the mobile-only wording when codes are sent by email.
$("phoneHelp").textContent = (CFG.otpChannel === "sms" ? "We send a one-time code to this number to confirm it. " : "We send a one-time code to your email to confirm your account. ") + "One account per number.";

// Tell a first-time visitor where to start, without showing any secret.
if (CFG.needsAdmin) $("setupHint").innerHTML = '<div class="msg"><b>First-time setup.</b> No administrator exists yet. Open a terminal in the project folder and run <span class="mono">./run.sh</span>, it asks for the first admin. <a href="guide.html">Guided tour</a></div>';
else if (CFG.devLogins) $("setupHint").innerHTML = '<div class="msg"><b>Looking for a login?</b> Development logins are generated on this computer. Run <span class="mono">python backend/manage.py logins</span> or open <span class="mono">data/demo_credentials.txt</span>. One-time codes arrive at <a href="http://localhost:8025" target="_blank">localhost:8025</a>. <a href="guide.html">Guided tour</a></div>';

// Google Authentication
function initGoogleAuth() {
  const cid = (window.SKYCLEAR && window.SKYCLEAR.googleClientId) || (window.CFG && window.CFG.googleClientId);
  if (!cid || !window.google) return;
  const wrap = $("googleAuthWrap");
  if (wrap) wrap.classList.remove("hidden");
  try {
    google.accounts.id.initialize({
      client_id: cid,
      callback: handleGoogleCredential,
    });
    const theme = document.documentElement.dataset.theme === "dark" ? "filled_black" : "outline";
    google.accounts.id.renderButton($("g_id_signin"), {
      type: "standard",
      theme: theme,
      size: "large",
      width: 280,
      text: "continue_with",
      shape: "rectangular",
    });
  } catch (err) {
    console.warn("Google identity init error:", err);
  }
}

async function handleGoogleCredential(response) {
  try {
    const r = await api("/auth/google", {
      method: "POST",
      auth: false,
      body: { credential: response.credential },
    });
    finish(r);
  } catch (err) {
    fail("signinMsg", err);
  }
}

if (window.google) initGoogleAuth();
else window.addEventListener("load", initGoogleAuth);

