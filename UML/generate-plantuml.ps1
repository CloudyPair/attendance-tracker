# Path to PlantUML JAR
$PlantUmlJar = "C:\Users\Alex\AppData\Roaming\Code\User\globalStorage\justuskarlsson.plan-uml\plantuml-1.2025.10.jar"

# Root directory: current directory
$Root = Get-Location

# Check Java
try {
    java -version 2>&1 | Out-Null
}
catch {
    Write-Error "Java was not found. Make sure Java is installed and available in PATH."
    exit 1
}

# Check PlantUML JAR
if (-not (Test-Path $PlantUmlJar)) {
    Write-Error "PlantUML JAR not found:"
    Write-Error $PlantUmlJar
    exit 1
}

# Find every .puml recursively
$Files = Get-ChildItem `
    -Path $Root `
    -Filter "*.puml" `
    -File `
    -Recurse

if ($Files.Count -eq 0) {
    Write-Host "No .puml files found."
    exit 0
}

Write-Host ""
Write-Host "Found $($Files.Count) PlantUML files."
Write-Host ""

$Success = 0
$Failed = 0

foreach ($File in $Files) {

    Write-Host "Rendering: $($File.FullName)"

    # PlantUML outputs the SVG next to the source file
    & java -jar $PlantUmlJar `
        $File.FullName `
        -tsvg

    if ($LASTEXITCODE -eq 0) {
        $SvgPath = [System.IO.Path]::ChangeExtension(
            $File.FullName,
            ".svg"
        )

        if (Test-Path $SvgPath) {
            Write-Host "  OK -> $SvgPath" -ForegroundColor Green
            $Success++
        }
        else {
            Write-Host "  FAILED: SVG was not created" -ForegroundColor Red
            $Failed++
        }
    }
    else {
        Write-Host "  FAILED: PlantUML returned exit code $LASTEXITCODE" -ForegroundColor Red
        $Failed++
    }

    Write-Host ""
}

Write-Host "========================================"
Write-Host "Finished"
Write-Host "========================================"
Write-Host "Successful: $Success"
Write-Host "Failed:     $Failed"
Write-Host "Total:      $($Files.Count)"