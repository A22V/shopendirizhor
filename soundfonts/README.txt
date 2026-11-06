TimGM6mb.sf2 is a small free General MIDI soundfont (GNU GPL v2, packaged by Debian as timgm6mb-soundfont).
It is included only so that audio previews work out of the box; its quality is modest.
For a better preview put a larger .sf2 file (for example FluidR3_GM.sf2) into this folder: the program uses the largest .sf2 it finds here.

MS Basic.sf3 (51 MB) is the default soundfont of MuseScore 4 (based on MuseScore_General_HQ v0.2 by Frank Wen,
Michael Cowgill and S. Christian Collins; released under the MIT license, as stated inside the file).
Added 2026-11-06 from the user's MuseScore installation so that MP3 previews sound like MuseScore.
The program tries the largest bank first; if rendering fails (for example, not enough memory in the cloud),
audio_tools.render_wav falls back to the next bank (TimGM6mb.sf2).
