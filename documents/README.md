# Documents

Drop your source files in here directly (no subfolders needed unless you want them):
CV/resume, diplomas/certificates, a LinkedIn profile export or PDF, anything else you
want available as reference material for the content engine.

**Nothing in this folder is committed to git** (see the root `.gitignore` — only this
README is tracked) since these files typically carry personal details (full legal
name, address, exam results, dates of birth) that shouldn't end up in a repo. They stay
local to this machine.

When you add something here, just tell me ("I've added my CV" / "check the diploma I
put in documents/") and I'll read it and pull the relevant facts into
`linkedin_content_engine/linkedin_content_engine/context/about_me.md` — the structured,
living summary the drafting engine actually draws on. The raw files themselves aren't
fed to any drafting call directly; they're a source I read once and summarise from.
