<div style="max-width: 800px; margin: 40px auto; padding: 30px; background-color: #1e1e1e; border-radius: 12px; color: #ddd; line-height: 1.6;">

  <h2 style="text-align: center; color: #ff4444;">Ready to Enter the Arena?</h2>
  
  <p style="text-align: center; font-size: 18px; margin: 20px 0;">
    Download the installer and follow the prompts below
  </p>

  <!-- Download Button -->
  <div style="text-align: center; margin: 30px 0;">
    <a href="https://raw.githubusercontent.com/bkstafford1971/Bloodspire/main/Bloodspire_Installer.exe"
       class="download-btn"
       download="Bloodspire_Installer.exe"
       style="display: inline-block; background-color: #238636; color: white; padding: 16px 32px; 
              font-size: 20px; font-weight: bold; text-decoration: none; border-radius: 10px; 
              box-shadow: 0 4px 12px rgba(0,0,0,0.3); transition: all 0.2s;">
      ↓ Download Bloodspire Installer (.exe)
    </a>
  </div>

  <p style="text-align: center; color: #aaa; font-size: 15px;">
    <strong>Important:</strong> Do Not change the default install directory
  </p>

  <hr style="border-color: #333; margin: 40px 0;">

  <h3 style="color: #ffaa00;">Once Installed</h3>
  <p>You will need to go to the <a href="https://tailscale.com/" target="_blank" style="color: #58a6ff;">Tailscale website</a> and create a free account.</p>

  <h3 style="color: #ffaa00;">Launch the Game</h3>
  <ol style="padding-left: 20px;">
    <li>Open <strong>C:\Bloodspire</strong> in Windows Explorer</li>
    <li>Double-click <strong>START_GAME.bat</strong></li>
    <li>A command window will open — <strong>leave it running in the background</strong></li>
    <li>Your browser should open automatically to the Bloodspire client</li>
  </ol>

  <h3 style="color: #ffaa00;">Connect to the League Server</h3>
  <ol style="padding-left: 20px;">
    <li>In the Bloodspire client, click the <strong>Action</strong> menu at the top</li>
    <li>Select <strong>Account Settings...</strong></li>
    <li>In the <strong>League Server URL</strong> field, enter:<br>
      <code style="background:#2d2d2d; padding: 8px; display:block; margin:10px 0; border-radius:6px; font-family: monospace;">
        http://100.114.138.61:8766
      </code>
    </li>
    <li>Click <strong>Connect</strong> (or save the settings)</li>
    <li>You should see a connection confirmation</li>
  </ol>
  <p style="color: #ff6666; font-weight: bold;">
    <strong>Note:</strong> You must have Tailscale running and your share accepted before this URL will work.
  </p>

  <h3 style="color: #ffaa00;">Create Your Account and Team</h3>
  <ol style="padding-left: 20px;">
    <li>On the login screen, choose <strong>New Player</strong> and fill in your details</li>
    <li>After logging in, click <strong>New Team</strong> to create your roster</li>
    <li>Build your team — assign warrior names, races, attributes, and equipment</li>
    <li>When ready, go to <strong>Action → Upload</strong> to submit your team to the league</li>
    <li>After the league admin runs a turn, go to <strong>Action → Download</strong> to get your results</li>
  </ol>

  <h3 style="color: #ffaa00;">How a Turn Works</h3>
  <ul style="padding-left: 20px;">
    <li>The league admin runs turns on a set schedule</li>
    <li>Before each turn deadline, <strong>Upload</strong> your team with any strategy changes</li>
    <li>After the turn runs, <strong>Download</strong> your results to see fight narratives, standings, and the newsletter</li>
    <li>Read the <strong>Arena Newsletter</strong> under the Newsletters tab for the full turn recap</li>
  </ul>

  <h3 style="color: #ffaa00;">Troubleshooting</h3>
  <details style="margin-bottom: 15px;">
    <summary style="cursor: pointer; color: #58a6ff;"><strong>The game won't start / START_GAME.bat closes immediately</strong></summary>
    <p style="margin: 10px 0 0 20px;">Make sure Python 3 is installed and was added to PATH.<br>
    Open Command Prompt, go to <code>C:\Bloodspire</code>, and run <code>python gui_server.py</code> to see errors.</p>
  </details>

  <details style="margin-bottom: 15px;">
    <summary style="cursor: pointer; color: #58a6ff;"><strong>Can't connect to the league server</strong></summary>
    <p style="margin: 10px 0 0 20px;">Make sure Tailscale is installed, running, and your share invite has been accepted.<br>
    Double-check the server URL is exactly <code>http://100.114.138.61:8766</code></p>
  </details>

  <details>
    <summary style="cursor: pointer; color: #58a6ff;"><strong>Browser doesn't open automatically</strong></summary>
    <p style="margin: 10px 0 0 20px;">Manually go to <code>http://localhost:8765</code> in any browser.</p>
  </details>

  <hr style="border-color: #333; margin: 40px 0;">

  <p style="text-align: center; font-size: 18px;">
    Questions or Issues? Email the league admin at 
    <a href="mailto:bkstafford1971@gmail.com" style="color: #58a6ff;">bkstafford1971@gmail.com</a>
  </p>

  <p style="text-align: center; font-size: 22px; color: #ffaa00; margin-top: 30px;">
    Good luck in the arena!
  </p>

</div>
