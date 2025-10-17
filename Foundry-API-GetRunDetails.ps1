$dotenvPath = Join-Path $PSScriptRoot '.env'
if (Test-Path $dotenvPath) {
  Get-Content $dotenvPath | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $eq = $line.IndexOf('=')
    if ($eq -lt 1) { return }
    $k = $line.Substring(0,$eq).Trim()
    $v = $line.Substring($eq+1).Trim().Trim('"').Trim("'")
    if (-not [string]::IsNullOrWhiteSpace($k) -and -not $env:$k) { $env:$k = $v }
  }
}
if (-not $env:BASE_URL) { throw "Missing BASE_URL in environment or .env file" }


$Base = $env:BASE_URL
$Project = "aisa-v2k5xehcjn65c-project"
$ThreadId = "thread_nX6dV9OaFfFbX63eQ1Rcn24Z"
$RunId = "run_m3cif3VEaFuY2IOBVoZcDX4y"
$ApiVersion = "v1"
$Token = (az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)

@'
{
  "tool_approvals": [
    {
      "tool_call_id": "call_B81AcWb1tLZRoNXkAEER8PUk",
      "approve": true
    }
  ]
}
'@ | Set-Content -Path tool_approvals.json -Encoding UTF8


# Build URL via format string
$RunUrl = ("{0}/api/projects/{1}/threads/{2}/runs/{3}?api-version={4}" -f $Base, $Project, $ThreadId, $RunId, $ApiVersion)

if ($RunUrl -notmatch '\?api-version=') {
    throw "api-version parameter missing from URL: $RunUrl"
}

Write-Host "GET Run URL: $RunUrl"
Write-Host "Token first 30: $($Token.Substring(0,30))..."

#$RunUrl = "$Base/api/projects/$Project/threads/$ThreadId/runs/$RunId?api-version=$ApiVersion"
Write-Host "GET Run URL: $RunUrl"
curl.exe --request GET `
  --url $RunUrl `
  -H "Authorization: Bearer $Token" `
  -H "Content-Type: application/json"


#curl --request POST `
 # --url "$Base/api/projects/$Project/threads/$ThreadId/runs/$RunId/submit_tool_outputs?api-version=$ApiVersion" `
  #-H "Authorization: Bearer $Token" `
  #-H "Content-Type: application/json" `
  #--data @tool_approvals.json