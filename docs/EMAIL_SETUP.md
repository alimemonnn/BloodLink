# Email: why nothing arrives, and how to fix it

BloodLink sends three kinds of email: **password reset**, **email confirmation**, and **donor alerts** (only to donors who
ticked "email me"). They all need an outgoing mail (SMTP) account. Until you add one:

* the password-reset and confirmation **links are printed in the terminal** where `python app.py` is running
  (look for `DEV MAIL`). Copy the link into your browser. Nothing goes to any inbox.
* the seeded demo accounts use fake addresses such as `ahmed.ali@example.com`, which can never receive mail.
  To test a real inbox, **register a new account with your own email address**.

## Turn on real email (Gmail, about 3 minutes)

1. Google Account > **Security** > turn on **2-Step Verification**.
2. Search "App passwords", create one called BloodLink, copy the 16 letters.
3. In the project folder copy `.env.example` to `.env` and fill in:
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=yourname@gmail.com
   SMTP_PASSWORD=the-16-letter-app-password
   SMTP_FROM=BloodLink <yourname@gmail.com>
   PUBLIC_BASE_URL=http://127.0.0.1:5000
   ```
4. Stop the app (Ctrl+C), run `pip install -r requirements.txt` once (adds `.env` support), then `python app.py`.
5. Register with your own email, open **Forgot your password?**, and check the inbox (and Spam).

Other providers work the same way: Brevo, SendGrid, Mailgun, Outlook, or your university's SMTP. Use port **587**
(default), or port **465** with `SMTP_SECURITY=ssl`. Connections are always encrypted and the server certificate is checked;
there is no plain-text option on purpose.

On **Render**, add the same variables under *Environment* and set `PUBLIC_BASE_URL` to your live https address.

## If it still does not arrive

| Symptom | Likely cause |
|---|---|
| Terminal shows `email ... failed: SMTPAuthenticationError` | Wrong user or password. For Gmail use the App Password, not your normal one. |
| `SMTPNotSupportedError` or a timeout | Wrong port. Try 587, or 465 with `SMTP_SECURITY=ssl`. Some networks block outgoing SMTP. |
| `SSLCertVerificationError` / `CERTIFICATE_VERIFY_FAILED` | The server certificate is not trusted, often antivirus or a campus proxy intercepting TLS. |
| Page says "we have sent a link" but nothing arrives | The address has no account (we answer the same either way, on purpose). Check Spam. |
| Donor alert emails never arrive | The donor must tick "email me" in privacy choices, and `PUBLIC_BASE_URL` must be set. |
| Nothing in the terminal either | The app was started without the project's `.env`, or from a different folder. |
