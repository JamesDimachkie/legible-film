# Security

Legible Film runs on your machine. The parts that listen on a network port do so only on 127.0.0.1:

- The Screening Room's live mode (`screen.py serve`) sits behind a private link made for that session, serves only
  the room's own files and refuses requests for another host.
- The film kit's tools (`film_check.py`, `film_render.py`, `make_film.py`) serve the film folder (the renderer, a
  frozen copy of it) to their own headless browser while they run.

Nothing is uploaded unless you ask for it; the skill asks before anything leaves the machine.

## Reporting a vulnerability

Report it privately through GitHub's private vulnerability reporting on this repository (the Security tab, "Report a
vulnerability"), not in a public issue. If that form is not offered, open an issue that asks for a private contact and
leaves out the details. Say which script and command, what an attacker could reach or change, and the version
(`skills/legible-film/SKILL.md`, `metadata.version`). Leave out private footage and personal data; a synthetic file that
reproduces the problem is enough.
