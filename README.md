# OneDrive Uploader CLI

A command-line tool to upload files to a specific user's OneDrive using Microsoft Graph API with app-only authentication. Ideal for automated scripts, backups, or any process without user interaction.

## Installation

### Using `pipx` (Recommended)

The easiest way to install the tool is with `pipx`, which installs it in an isolated environment.

```sh
pipx install git+https://github.com/sumanmichael/onedriveuploader.git
```

### Using `pip` (from source)

If you want to install it from a local clone (e.g., for development):

```sh
git clone https://github.com/sumanmichael/onedriveuploader.git
cd onedriveuploader
pip install .
```

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

### 3. Run the Uploader

Once configured, you can run the tool from any directory.

#### Basic Upload

To upload a file to the root of the target user's OneDrive:

```sh
onedriveuploader "/path/to/your/local/file.txt"
```

#### Upload to a Specific Folder

To upload a file to a specific folder (e.g., `Documents/Backups`), use the `-d` or `--destination` flag. If the folder does not exist, it will be created.

```sh
onedriveuploader "/path/to/server-backup.zip" -d "Server/DailyBackups"
```

## License

This project is licensed under the MIT License. See the LICENSE file for details.
