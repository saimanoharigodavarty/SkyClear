// Sign in, register, one-time codes and the authenticator step for officials.
header(null);
const params = new URLSearchParams(location.search);
const forms = ["signinForm", "registerForm", "otpForm", "otpAskForm", "mfaForm"];
let otpIdentifier = "", mfaToken = "", tab = params.get("tab") === "register" ? "register" : "signin";

function show(name) {
  forms.forEach(f => $(f).classList.toggle("hidden", f !== name));
  const top = name === "signinForm" || name === "registerForm";
  $("tabs").classList.toggle("hidden", !top);
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.t === (name === "registerForm" ? "register" : "signin")));
  const titles = { signinForm: "Sign in to SkyClear", registerForm: "Create your pilot account", otpForm: "Check your phone", otpAskForm: "Sign in with a code", mfaForm: "One more step" };
  $("title").textContent = titles[name];
  $("lead").classList.toggle("hidden", !top);
}
document.querySelectorAll("#tabs button").forEach(b => b.addEventListener("click", () => show(b.dataset.t === "register" ? "registerForm" : "signinForm")));
if (params.get("expired")) $("notice").innerHTML = '<div class="msg">Your session ended. Please sign in again.</div>';
show(tab === "register" ? "registerForm" : "signinForm");

const fail = (id, e) => { $(id).innerHTML = `<div class="msg err" role="alert">${esc(e.message)}</div>`; };
function finish(t) {
  setSession(t);
  const next = params.get("next");
  location.href = next || (t.user.role === "official" ? "official.html" : "index.html");
}
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
    if (err.message === "phone_not_verified") {
      try { const o = await api("/auth/otp/request", { method: "POST", auth: false, body: { identifier: $("lId").value } }); return showCode(o, "Your mobile number is not confirmed yet. We sent you a code."); }
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
    showCode(r, "We sent a 6-digit code to " + r.identifier + ". Enter it to finish creating your account.");
  } catch (err) { fail("registerMsg", err); }
});

$("otpForm").addEventListener("submit", async e => {
  e.preventDefault();
  try { finish(await api("/auth/otp/verify", { method: "POST", auth: false, body: { identifier: otpIdentifier, code: $("otpCode").value } })); }
  catch (err) { fail("otpMsg", err); }
});
$("resend").addEventListener("click", async () => {
  try { const o = await api("/auth/otp/request", { method: "POST", auth: false, body: { identifier: otpIdentifier } }); showCode(o, "We sent a new code to " + otpIdentifier + "."); }
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
    showCode({ ...o, identifier: o.identifier || $("oId").value }, "If a pilot account matches, we sent a 6-digit code to that mobile number.");
  } catch (err) { fail("otpAskMsg", err); }
});

document.querySelectorAll("[data-demo]").forEach(b => b.addEventListener("click", () => {
  const [id, pw] = b.dataset.demo.split("|"); show("signinForm"); $("lId").value = id; $("lPass").value = pw; $("lPass").focus();
}));
