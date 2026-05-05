Install the latest PowerShell for new features and improvements! https://aka.ms/PSWindows

PS C:\Bloodspire-Electron> npm run make

> bloodspire@1.0.0 make
> electron-forge make

✔ Checking your system
✔ Loading configuration
✔ Resolving make targets
  › Making for the following targets: ,
✔ Running package command
  ✔ Preparing to package application
  ✔ Running packaging hooks
    ✔ Running generateAssets hook
    ✔ Running prePackage hook
      ✔ [plugin-webpack] Preparing webpack bundles
        ✔ Preparing native dependencies [0.3s]
        ✔ Building webpack bundles [2s]
  ✔ Packaging application
    ✔ Packaging for x64 on win32 [4s]
  ✔ Running postPackage hook
✔ Running preMake hook
✔ Making distributables
  ✔ Making a squirrel distributable for win32/x64 [41s]
  ✔ Making a zip distributable for win32/x64 [15s]
✔ Running postMake hook
  › Artifacts available at: C:\Bloodspire-Electron\out\make

(node:18364) [DEP0147] DeprecationWarning: In future versions of Node.js, fs.rmdir(path, { recursive: true }) will be removed. Use fs.rm(path, { recursive: true }) instead
(Use `node --trace-deprecation ...` to show where the warning was created)
PS C:\Bloodspire-Electron>