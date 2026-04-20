To play download the installer and follow the prompts

<div style="text-align: center; margin: 40px 0;">
  <h2>Ready to Enter the Arena?</h2>
  <p>Download the latest version for Windows</p>
 
  <a href="https://raw.githubusercontent.com/bkstafford1971/Bloodspire/main/Bloodspire_Installer.exe" 
     class="download-btn" 
     download="Bloodspire_Installer.exe">
    ↓ Download Bloodspire Installer (.exe)
  </a>
 
  <p style="margin-top: 20px; color: #888; font-size: 14px;">
    Includes everything you need — just run the installer and play!
  </p>
</div>

Do Not change the default install directory

Once the files are installed, you will need to go to the tailscale site to create a free account.  

## Launch the Game

1. Open `C:\Bloodspire` in Windows Explorer
2. Double-click **START_GAME.bat**
3. A command window will open — **leave it running in the background**
4. Your browser should open automatically to the Bloodspire client

## Connect to the League Server

1. In the Bloodspire client, click the **Action** menu at the top
2. Select **Account Settings...**
3. In the **League Server URL** field, enter:

```
http://100.114.138.61:8766
```

4. Click **Connect** (or save the settings)
5. You should see a connection confirmation — you're now linked to the live league!

> **Note:** You must have Tailscale running and your share accepted before this URL will work.

---

##  Create Your Account and Team

1. On the login screen, choose **New Player** and fill in your details
2. After logging in, click **New Team** to create your roster
3. Build your team — assign warrior names, races, attributes, and equipment
4. When ready, go to **Action → Upload** to submit your team to the league
5. After the league admin runs a turn, go to **Action → Download** to get your results

---

## How a Turn Works

- The league admin runs turns on a set schedule
- Before each turn deadline, **Upload** your team with any strategy changes
- After the turn runs, **Download** your results to see fight narratives, standings, and the newsletter
- Read the **Arena Newsletter** under the Newsletters tab for the full turn recap

---

## Troubleshooting

**The game won't start / START_GAME.bat closes immediately**
- Make sure Python 3 is installed and was added to PATH during installation
- Open a Command Prompt, navigate to `C:\Bloodspire`, and run `python gui_server.py` manually to see any error messages

**Can't connect to the league server**
- Make sure Tailscale is installed, running, and your share invite has been accepted
- Double-check the server URL is exactly `http://100.114.138.61:8766`
- Try pinging the server from Tailscale's status screen

**Browser doesn't open automatically**
- Manually navigate to `http://localhost:8765` in any browser

---

## Questions or Issues?

Email the league admin at **bkstafford1971@gmail.com**

Good luck in the arena!
