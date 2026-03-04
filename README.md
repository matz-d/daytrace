# AGI Lab Skills Marketplace

Claude Code skills curated by [AGI Lab](https://agilab.jp).

## Install

```bash
# In Claude Code:
/plugin marketplace add kaishushito/agi-lab-skills-marketplace
/plugin install terminal-vibes@agi-lab-skills
```

## Available Plugins

### terminal-vibes

Bring fun to your terminal! No API keys needed.

| Command | What it does |
|---------|-------------|
| `/vibes` | Random terminal entertainment |
| `/vibes donut` | Spinning 3D ASCII donut |
| `/vibes cat` | Random ASCII cat art |
| `/vibes joke` | Programmer dad jokes raining down |
| `/vibes matrix` | Matrix-style digital rain |
| `/vibes full show` | All acts in sequence |

**Requirements**: Python 3, Bash, modern terminal with ANSI support.

## Adding Your Own Skills

Want to contribute? Add a plugin under `plugins/` following this structure:

```
plugins/your-plugin/
├── .claude-plugin/
│   └── plugin.json
└── skills/
    └── your-skill/
        └── SKILL.md
```

Then add an entry to `.claude-plugin/marketplace.json`.

## License

MIT
