; Skrip Inno Setup (https://jrsoftware.org/isinfo.php) -- BELUM DIUJI di lingkungan ini.
; Pakai setelah `python build.py` (mode folder): buka berkas ini di Inno Setup Compiler lalu Compile.
; Installer dibagikan sebagai SATU berkas; berkas aplikasi yang terpasang tidak membawa
; tanda "Mark of the Web" dari unduhan, jadi tidak diblokir satu-per-satu oleh SmartScreen.
; Sebaiknya installer ini JUGA ditandatangani (lihat bagian SignTool di bawah).

#define NamaApp "Modbus Tools Kalingin"
#define Versi "18.0"
#define Penerbit "Kalingin"
#define Exe "ModbusToolsKalingin.exe"

[Setup]
AppName={#NamaApp}
AppVersion={#Versi}
AppPublisher={#Penerbit}
DefaultDirName={autopf}\ModbusToolsKalingin
DefaultGroupName={#NamaApp}
OutputDir=dist_installer
OutputBaseFilename=ModbusToolsKalingin_Setup_v{#Versi}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#Exe}
; Aktifkan jika sudah punya sertifikat (definisikan 'tandatangan' di Tools > Configure Sign Tools):
; SignTool=tandatangan $f

[Tasks]
Name: "desktopicon"; Description: "Buat ikon di Desktop"; Flags: unchecked

[Files]
Source: "dist\ModbusToolsKalingin\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#NamaApp}"; Filename: "{app}\{#Exe}"
Name: "{autodesktop}\{#NamaApp}"; Filename: "{app}\{#Exe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Exe}"; Description: "Jalankan {#NamaApp}"; Flags: nowait postinstall skipifsilent
