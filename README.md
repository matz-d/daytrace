# AGI Lab Skills Marketplace

Claude Code plugins curated by [AGI Lab](https://agilab.jp).

This repository now serves two purposes:

1. Install ready-made plugins from AGI Lab
2. Use the `hackathon-starter` plugin as a template for the AGIラボ AIエージェントハッカソン

## Install Existing Plugins

```bash
# In Claude Code:
/plugin marketplace add kaishushito/agi-lab-skills-marketplace
/plugin install terminal-vibes@agi-lab-skills
```

## For Hackathon Participants

If you are joining the AGI Lab hackathon, this repo can be your starting point.

### Start Here

1. Fork this repository
2. Use `plugins/hackathon-starter/` as your base
3. Rename the plugin and skill to match your idea
4. Replace the starter text with your own workflow
5. Push your repo publicly on GitHub
6. Submit your repo URL and demo video

### Minimum Files To Touch

- `.claude-plugin/marketplace.json`
- `plugins/hackathon-starter/.claude-plugin/plugin.json`
- `plugins/hackathon-starter/skills/starter-guide/SKILL.md`
- `README.md`

### What Judges Will Try

Your submission should be installable with:

```bash
/plugin marketplace add <your-github-user>/<your-repo>
/plugin install <your-plugin-name>@<your-marketplace-name>
```

If the repo is public and the plugin installs cleanly, judges can try it quickly.

### Good Enough For Submission

You do not need a giant framework.

- One public GitHub repo
- One plugin
- One clear skill
- A short README
- A demo video within 3 minutes

That is enough to submit.

## Available Plugins

### hackathon-starter

Starter plugin for hackathon participants.

Use this when you want a minimal example of:

- plugin structure
- marketplace entry
- skill frontmatter
- README expectations

### terminal-vibes

Bring fun to your terminal. No API keys needed.

| Command | What it does |
|---------|-------------|
| `/vibes` | Random terminal entertainment |
| `/vibes donut` | Spinning 3D ASCII donut |
| `/vibes cat` | Random ASCII cat art |
| `/vibes joke` | Programmer dad jokes raining down |
| `/vibes matrix` | Matrix-style digital rain |
| `/vibes full show` | All acts in sequence |

**Requirements**: Python 3, Bash, modern terminal with ANSI support.

## Repository Structure

```text
.claude-plugin/
└── marketplace.json

plugins/
├── hackathon-starter/
│   ├── .claude-plugin/
│   │   └── plugin.json
│   └── skills/
│       └── starter-guide/
│           └── SKILL.md
└── terminal-vibes/
    ├── .claude-plugin/
    │   └── plugin.json
    ├── scripts/
    └── skills/
```

## License

MIT
