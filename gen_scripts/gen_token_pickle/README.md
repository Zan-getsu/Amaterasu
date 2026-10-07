# Google Desktop app token generator

Run this on your own computer (Python 3.10+), with the browser on the same
computer. Desktop OAuth uses a local loopback callback, not the bot's Web URL.

## Token lifetime

Desktop clients do not automatically get longer-lived tokens. Google's
External projects in **Testing** issue refresh tokens that expire after
**7 days** when requesting Drive scopes. For longer-lived access, change
Google Cloud Console > Google Auth Platform > Audience to **In production**,
then generate a fresh token. Follow Google's verification requirements where
applicable. Tokens can still expire or be revoked; no permanent lifetime is guaranteed.
The bot refreshes short-lived access tokens using the refresh token.

Official reference: https://developers.google.com/identity/protocols/oauth2#expiration

## Standalone Desktop script

1. Copy this script into a private folder on your computer.
2. Enable Google Drive API in your Google Cloud project.
3. Configure the OAuth audience and consent screen. If still Testing, add your
   account as a test user (the seven-day limit still applies).
4. Create an OAuth client ID of type **Desktop app**, download its JSON, and
   place it beside `script.py` as `credentials.json`.
5. Open a terminal in that folder:

```powershell
python -m pip install google-auth-oauthlib
python script.py --credentials credentials.json --output token.pickle --scopes https://www.googleapis.com/auth/drive
```

6. Complete authorization in your local browser. If the browser does not open,
   open the printed URL on the same computer. The script waits up to five minutes.
7. In Telegram, open `/userset > GDrive Tools > TOKEN.PICKLE` and upload
   `token.pickle`. This replaces your active bot token; the token saved by the
   Web generator remains separate. Owners may place it at the bot's configured
   `token.pickle` path instead.

Only load tokens you generated yourself. Keep credentials, tokens, and printed
OAuth URLs private. Desktop credentials cannot use the hosted Web form.

## Running from this repository

```powershell
python -m pip install google-auth-oauthlib
python gen_scripts/gen_token_pickle/script.py
```

Without flags, paths resolve from the script location:
`gen_scripts/config/credentials.json` and `gen_scripts/tokens/token.pickle`.
The default Drive + YouTube scopes are preserved for the existing setup scripts.
Use the explicit Drive-only command above for Amaterasu.
Existing valid tokens are reused; expired tokens are refreshed where possible.
Move an old token aside or choose a new `--output` path to force new authorization
(e.g. after changing the OAuth project or publishing status).

Console copy/paste authorization is no longer used. If sign-in fails, check the
Desktop client type, Drive API, audience/test users, network, and local firewall,
then rerun on a computer with a browser.
