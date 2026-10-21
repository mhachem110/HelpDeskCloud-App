#!/usr/bin/env bash
set -euo pipefail

# CI and the protected release package must validate the same reviewed source.
# Keeping these commands in one helper prevents either path from losing a test.
dotnet restore src/HelpDeskCloud/HelpDeskCloud.csproj
dotnet restore tests/HelpDeskCloud.Tests/HelpDeskCloud.Tests.csproj
dotnet build src/HelpDeskCloud/HelpDeskCloud.csproj -c Release --no-restore
dotnet run --project tests/HelpDeskCloud.Tests/HelpDeskCloud.Tests.csproj -c Release --no-restore
