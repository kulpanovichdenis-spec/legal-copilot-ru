# Codex repo skills

Codex discovers repository skills under `.agents/skills`. The canonical skill files in this project remain under `skills/` so Claude and other runners keep using the existing layout.

On Windows, create the local NTFS junction without duplicating files:

```powershell
powershell -ExecutionPolicy Bypass -File tools/setup_codex_skills.ps1
```

The generated `.agents/skills` path is ignored by Git. The setup script refuses to replace an existing file, directory, or link whose target is not the project `skills/` directory.

On Linux or macOS, the equivalent command is:

```bash
mkdir -p .agents
ln -s ../skills .agents/skills
```
