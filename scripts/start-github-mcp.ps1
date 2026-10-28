$ErrorActionPreference = 'Stop'

# Use the existing credential store; never persist or print the token.
$githubToken = & gh auth token --hostname github.com 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($githubToken)) {
    throw 'GitHub CLI authentication unavailable. Authenticate with gh auth login first.'
}

try {
    $env:GITHUB_MCP_AUTH = 'Bearer ' + $githubToken.Trim()
    $githubToken = $null
    & npx.cmd --yes mcp-remote@0.15.2 'https://api.githubcopilot.com/mcp/' --header 'Authorization:${GITHUB_MCP_AUTH}'
    $serverExitCode = $LASTEXITCODE
} finally {
    Remove-Item Env:GITHUB_MCP_AUTH -ErrorAction SilentlyContinue
    $githubToken = $null
}
exit $serverExitCode
