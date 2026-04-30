Perfect — thank you for the screenshot and confirmation.

Your **BLOODSPIRE Client** connects to the server using a **Server URL** field, and it expects something like `http://localhost:8766`.  
This means the server on port 8766 is an **HTTP web service**. That's excellent news for Cloudflare Tunnel.

### What Users Will Do
Users will enter a **public HTTPS URL** (no custom port needed) into the Server URL field, for example:

`https://bloodspirearena.dpdns.org`

Cloudflare will handle the HTTPS encryption and forward the traffic to your local `http://localhost:8766`.

---

### Step-by-step: Set Up Cloudflare Tunnel (Recommended & Free)

#### 1. Install cloudflared on your Windows PC
- Download from: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
- Or run this in an **Administrator** Command Prompt:
  ```cmd
  winget install Cloudflare.cloudflared
  ```

#### 2. Login to Cloudflare
Open Command Prompt and run:
```cmd
cloudflared tunnel login
```
→ It will open a browser. Log in with the same Cloudflare account you used for your domain.

#### 3. Create the Tunnel
```cmd
cloudflared tunnel create bloodspire-arena
```
Copy the **Tunnel ID (UUID)** that it outputs.

#### 4. Create the config file
Create a folder if it doesn’t exist: `C:\Users\Bloodspire\.cloudflared`

Then create a new file named `config.yml` inside that folder with the following content:

```yaml
tunnel: YOUR-TUNNEL-UUID-HERE
credentials-file: C:\Users\Bloodspire\.cloudflared\YOUR-TUNNEL-UUID.json

ingress:
  - hostname: bloodspirearena.dpdns.org
    service: http://localhost:8766
  - service: http_status:404
```

**Replace** `YOUR-TUNNEL-UUID-HERE` with the actual UUID from step 3.

#### 5. Run the tunnel (for testing)
```cmd
cloudflared tunnel run --config C:\Users\Bloodspire\.cloudflared\config.yml bloodspire-arena
```

Keep this window open. The tunnel is now running.

#### 6. Add Public Hostname in Cloudflare Dashboard (Important!)
1. Go to https://dash.cloudflare.com
2. Select your domain **bloodspirearena.dpdns.org** (or dpdns.org)
3. Go to **Zero Trust** → **Networks** → **Tunnels**
4. Click on your tunnel → **Configure** → **Public Hostname** → **Add a public hostname**
5. Fill in:
   - **Subdomain**: `bloodspirearena` (or leave blank if you want the root)
   - **Domain**: `dpdns.org`
   - **Service**: `HTTP`
   - **URL**: `http://localhost:8766`  (or the internal IP of your PC if needed)
6. Save.

---

### Test It
Once the tunnel is running and the Public Hostname is added:
- On your PC, open a browser and go to: `https://bloodspirearena.dpdns.org`
- It should load the same page as `http://localhost:8766`

Then test from **another device** (phone on mobile data) using the same URL.

If it works, tell your users to put **`https://bloodspirearena.dpdns.org`** in the **Server URL** field of the BLOODSPIRE Client.

### Make the Tunnel Run Automatically (as a Service)
After testing, install it as a Windows service so it starts with Windows:

```cmd
cloudflared service install
```

---

Would you like me to give you the exact commands with placeholders replaced, or do you want to try the steps above first?

Also reply with:
- Did you already create a tunnel in the dashboard, or are you starting from scratch?
- Any error messages you get when running the commands?

We’re very close now — this should give you a clean public HTTPS URL without needing port forwarding or dealing with the double NAT.