# OneDrive Manager (odman)

A professional command-line tool to upload, download, and manage files in OneDrive using Microsoft Graph API with app-only authentication. Designed for automated scripts, backups, or any process requiring reliable OneDrive operations without user interaction.

## Installation

### Using `pipx` (Recommended)

The easiest way to install the tool is with `pipx`, which installs it in an isolated environment.

```sh
pipx install git+https://github.com/sumanmichael/odman.git
```

### Using `pip` (from source)

If you want to install it from a local clone (e.g., for development):

```sh
git clone https://github.com/sumanmichael/odman.git
cd odman
pip install .
```

## Features

✅ **Modular Architecture** - Clean, maintainable codebase with separated concerns  
✅ **Upload Operations** - Single files, directories, or mixed file/folder sets  
✅ **Download Operations** - Files and folders with recursive support  
✅ **List Operations** - Browse OneDrive contents with optional recursion  
✅ **Progress Tracking** - Rich progress bars and detailed operation summaries  
✅ **Parallel Processing** - Configurable concurrent workers (1-10)  
✅ **Robust Error Handling** - Retry logic with exponential backoff  
✅ **App-only Authentication** - No user interaction required

## Release and Changelog

This project follows [Semantic Versioning](https://semver.org/) and maintains a [CHANGELOG.md](CHANGELOG.md) with all notable changes.

### Automated Releases

Releases are automated using [Conventional Commits](https://www.conventionalcommits.org/):

- **fix:** commits trigger patch releases (0.1.0 → 0.1.1)
- **feat:** commits trigger minor releases (0.1.0 → 0.2.0)
- **feat!:** or **BREAKING CHANGE:** trigger major releases (0.1.0 → 1.0.0)

### Contributing

Please see [CONTRIBUTING.md](CONTRIBUTING.md) for commit message conventions and development guidelines.

## Usage Guide

### 1. Prerequisites: Microsoft Entra ID App Registration

Before using the tool, you need to register an application in Microsoft Entra ID (Azure AD) and grant it `Files.ReadWrite.All` **Application** permission for Microsoft Graph. An administrator must grant admin consent for this permission.

You will need to collect the following credentials from your app registration:

- **Application (client) ID**
- **Directory (tenant) ID**
- **Client Secret Value**
- **User ID** (The User Principal Name or Object ID of the target user)

### 2. Configure Environment Variables

The tool reads credentials from environment variables.

**Linux / macOS** (`~/.bashrc` or `~/.zshrc`):

```sh
export ONEDRIVE_CLIENT_ID="<Your_Application_Client_ID>"
export ONEDRIVE_TENANT_ID="<Your_Directory_Tenant_ID>"
export ONEDRIVE_CLIENT_SECRET="<Your_Client_Secret_Value>"
export ONEDRIVE_USER_ID="<Target_User_ID_or_Email>"
```

**Windows (PowerShell)**:

```powershell
$env:ONEDRIVE_CLIENT_ID="<Your_Application_Client_ID>"
$env:ONEDRIVE_TENANT_ID="<Your_Directory_Tenant_ID>"
$env:ONEDRIVE_CLIENT_SECRET="<Your_Client_Secret_Value>"
$env:ONEDRIVE_USER_ID="<Target_User_ID_or_Email>"
```

Remember to reload your shell or open a new terminal to apply the changes.

### 3. Usage

Once configured, you can run the tool from any directory.

#### Upload

Upload files or folders to a user’s OneDrive.

##### Basic Upload

To upload a file to the root of the target user's OneDrive:

```sh
odman upload "/path/to/your/local/file.txt"
```

##### Upload to a Specific Folder

To upload a file to a specific folder (e.g., `Documents/Backups`), use the `-d` or `--destination` flag. If the folder does not exist, it will be created.

```sh
odman upload "/path/to/server-backup.zip" -r "Server/DailyBackups"
```

##### Upload Multiple Files

```sh
odman upload file1.txt file2.jpg file3.pdf
```

##### Options

- -r, --remote-folder: Destination path in OneDrive (folder will be created if missing)

- -c, --chunk-size: Upload chunk size in bytes (for large files)

- -w, --max-workers: Max number of parallel uploads (default: 3)

- --no-progress: Disable the progress bar

#### Download

Download files or folders from OneDrive.

##### Basic Download

```sh
odman download "Documents/Report.pdf"
```

##### Download Multiple Files

```sh
odman download "Reports/2023.pdf" "Photos/Vacation/"
```

##### Download to Specific Local Folder

```sh
odman download "Docs/" -l "./local_folder"
```

##### Options

- -l, --local-folder: Local folder to save downloaded files (default: ./downloads)

- -c, --chunk-size: Chunk size for downloads (in bytes)

- -w, --max-workers: Max number of parallel downloads (default: 3)

- --no-progress: Disable progress bar

#### List

List contents of a OneDrive folder.

##### Basic List

```sh
odman list
```

##### List a Specific Folder

```sh
odman list "Documents/Work"
```

##### Recursive Listing

```sh
odman list "Projects" -r
```

## License

This project is licensed under the MIT License. See the LICENSE file for details.
