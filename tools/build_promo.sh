#!/bin/bash
# ===========================================================================
# build_promo.sh — cut the promo video from captured frames.
#
# The footage is REAL: every 3D frame is the same three.js scene the champions
# page renders, from the same parts.json recipes and the same recorded replay,
# captured 2556x1436 and downscaled here. Nothing is mocked up.
#
# HOW THE FRAMES GET MADE (docs/Promo_Video_2026-08-18.md has the detail):
# the browser can produce the pixels but cannot write a file, and MediaRecorder
# is not usable — the automated tab is hidden, so requestAnimationFrame is
# suspended and setTimeout is throttled to ~1/s, meaning nothing can be
# recorded in real time. So the clock is driven by hand through __stage, each
# frame is read off the canvas with toDataURL, and POSTed to a tiny local
# collector that writes it to disk.
#
# ⚠ THIS FFMPEG HAS NO drawtext. It is built without libfreetype, so every
# piece of text here — title, captions, end card — is drawn on a CANVAS in the
# browser and composited as a PNG. That is also why the type matches the site.
#
#   usage: bash website/tools/build_promo.sh [FRAMEDIR] [OUTDIR]
# ===========================================================================
set -euo pipefail

FR="${1:-/tmp/promo_frames}"
OUT="${2:-/tmp/promo_out}"
IMG="$(cd "$(dirname "$0")/.." && pwd)/assets/img"
mkdir -p "$OUT"

W=1920; H=1080; FPS=30
# Common encode settings. yuv420p is not optional: without it Safari and
# QuickTime refuse the file outright, which is most of the audience.
# ⚠ crf 21, NOT 19. The film grew from one fight to four and the 1080p master
# went 10 MB -> 17 MB with it. At 24s that is ~5.7 Mbps for footage that is
# mostly flat dark floor and hard-edged geometry — more bitrate than the
# content can use. 21 costs nothing visible here and returns ~18%; 23 returns
# 35% and starts to smear the impact flares, which are the point.
ENC=(-c:v libx264 -preset slow -crf 21 -pix_fmt yuv420p -movflags +faststart -r $FPS)

say() { printf '  %s\n' "$1"; }

# ⚠ THE CUT ORDER IS THE POINT, AND THE FIRST VERSION GOT IT WRONG. That cut
# opened on a title card: 3.4 seconds passed before a single pixel of game
# content, and 6 of its 21 seconds were static text. A promo for a game whose
# whole appeal is watching machines hit each other cannot spend its first
# three seconds on typography — the viewer decides in about two.
#
# So it opens COLD on the impact, at frame zero, and the title lands after the
# hook rather than before it. The same blow then plays again in context, which
# is what the run-up is for. Cards are down from 6.2s to 4.0s of 18.8s.

# --- 0. cold open: the hit, at frame zero ---------------------------------
# Frames 118-149 straddle the peak. Fed at 20fps instead of the 30 they were
# captured at, so it reads as a slight slow motion rather than a clipped
# fragment.
say "cold open (the hit)"
ffmpeg -y -loglevel error -framerate 20 -start_number 118 -i "$FR/fight_%04d.jpg" \
  -frames:v 32 -vf "scale=$((W*12/10)):-2,crop=$W:$H:'(iw-ow)/2':'(ih-oh)/2',setsar=1,fade=t=out:st=1.35:d=0.25" \
  "${ENC[@]}" "$OUT/s0_cold.mp4"

# --- 1. title -------------------------------------------------------------
say "title card"
ffmpeg -y -loglevel error -loop 1 -i "$FR/card_title.png" -t 1.4 \
  -vf "scale=$W:$H,fade=t=in:st=0:d=0.3,fade=t=out:st=1.05:d=0.35,format=yuv420p" \
  "${ENC[@]}" "$OUT/s1_title.mp4"

# --- 2. the machine, turning ---------------------------------------------
# ⚠ -loop 1 ON THE CAPTION, AND IT IS NOT COSMETIC. A still image input is ONE
# frame at timestamp 0. `fade=t=in:st=0.6` asks for alpha 0 until 0.6s — and
# with a single frame the timestamp never reaches 0.6, so the overlay sits at
# alpha 0 for the whole shot and the caption is INVISIBLE. The first cut of
# this video shipped with no text on any shot for exactly that reason, and it
# looked like the overlay filter had simply been left out. -loop 1 gives the
# image advancing timestamps; overlay=shortest=1 then ends the segment with
# the footage rather than looping forever.
# ⚠ THIS SHOT USED TO BE A FINISHED ROBOT ROTATING, UNDER A CAPTION THAT SAYS
# "BOLT IT TOGETHER". Construction is the game's whole hook and the film never
# once showed it happening — it showed the result and asserted the process.
# These frames reveal the machine part by part IN THE ORDER THE PLAYER PLACED
# THEM, from the same recorded build, so the caption is now describing what is
# on screen rather than something the viewer has to take on trust.
say "assembly + caption"
ffmpeg -y -loglevel error -framerate $FPS -i "$FR/asm_%04d.jpg" -loop 1 -i "$FR/cap_build.png" \
  -frames:v 120 \
  -filter_complex "[0:v]scale=$W:$H,setsar=1[v];[1:v]scale=$W:$H,format=rgba,fps=$FPS,fade=t=in:st=0.4:d=0.4:alpha=1[c];[v][c]overlay=0:0:shortest=1,fade=t=in:st=0:d=0.3" \
  "${ENC[@]}" "$OUT/s2_build.mp4"

# --- 3. a second machine -------------------------------------------------
# ⚠ THIS SLOT USED TO BE A UI SCREENSHOT AND IT WAS THE WEAKEST SHOT IN THE
# FILM. The game's panels are dense tables; downscaled into a 1080p frame the
# text is illegible, so it read as a generic dark rectangle. A second, very
# differently shaped machine does the job the caption before it promises:
# "you choose every part" is a claim, and two machines that look nothing alike
# is the evidence.
say "second machine"
ffmpeg -y -loglevel error -framerate $FPS -i "$FR/mach2_%04d.jpg" -frames:v 72 \
  -vf "scale=$W:$H,setsar=1,fade=t=in:st=0:d=0.3,fade=t=out:st=2.1:d=0.3" \
  "${ENC[@]}" "$OUT/s3_mach2.mp4"

# --- 4. the fight, in full -----------------------------------------------
say "fight + caption"
ffmpeg -y -loglevel error -framerate $FPS -i "$FR/fight_%04d.jpg" -loop 1 -i "$FR/cap_fight.png" \
  -frames:v 100 \
  -filter_complex "[0:v]scale=$((W*12/10)):-2,crop=$W:$H:'(iw-ow)/2':'(ih-oh)/2',setsar=1[v];[1:v]scale=$W:$H,format=rgba,fps=$FPS,fade=t=in:st=0.3:d=0.4:alpha=1[c];[v][c]overlay=0:0:shortest=1,fade=t=in:st=0:d=0.25" \
  "${ENC[@]}" "$OUT/s4_fight.mp4"

# --- 4b. the montage: three more fights, three more machines --------------
# ⚠ THE FILM USED TO CONTAIN EXACTLY ONE FIGHT. It showed one pairing and then
# asked the viewer to believe in a five-class ladder — the machines a player
# might build were represented by two turntables and a single duel. These are
# three further REAL recorded matches from three different weight classes,
# each with a different pair of machines, captured the same way as everything
# else. Fight footage goes from 4.5s of 18.8 to ~12s of 24.
say "montage: LIGHT"
ffmpeg -y -loglevel error -framerate $FPS -i "$FR/fLIGHT_%04d.jpg" -loop 1 -i "$FR/cap_classes.png" \
  -frames:v 75 \
  -filter_complex "[0:v]scale=$((W*11/10)):-2,crop=$W:$H:'(iw-ow)/2':'(ih-oh)/2',setsar=1[v];[1:v]scale=$W:$H,format=rgba,fps=$FPS,fade=t=in:st=0.2:d=0.4:alpha=1[c];[v][c]overlay=0:0:shortest=1" \
  "${ENC[@]}" "$OUT/s4b_light.mp4"

say "montage: SUPER"
ffmpeg -y -loglevel error -framerate $FPS -i "$FR/fSUPER_%04d.jpg" -frames:v 75 \
  -vf "scale=$((W*11/10)):-2,crop=$W:$H:'(iw-ow)/2':'(ih-oh)/2',setsar=1" \
  "${ENC[@]}" "$OUT/s4c_super.mp4"

# HEAVY opens with the machines at opposite ends of the arena — its collision
# is in the SECOND half, so the shot starts there rather than on empty floor.
say "montage: HEAVY"
ffmpeg -y -loglevel error -framerate $FPS -start_number 40 -i "$FR/fHEAVY_%04d.jpg" -frames:v 50 \
  -vf "scale=$((W*11/10)):-2,crop=$W:$H:'(iw-ow)/2':'(ih-oh)/2',setsar=1,fade=t=out:st=1.4:d=0.25" \
  "${ENC[@]}" "$OUT/s4d_heavy.mp4"

# --- 5. the ladder -------------------------------------------------------
say "ladder screenshot + caption"
ffmpeg -y -loglevel error -loop 1 -i "$IMG/enlist.jpg" -loop 1 -i "$FR/cap_ladder.png" -t 2.8 \
  -filter_complex "[0:v]scale=$W:-2,pad=$W:$H:(ow-iw)/2:(oh-ih)/2:color=#0A0C11,zoompan=z='min(zoom+0.0007,1.07)':d=$((FPS*4)):s=${W}x${H}:fps=$FPS,setsar=1[v];[1:v]scale=$W:$H,format=rgba,fps=$FPS,fade=t=in:st=0.25:d=0.4:alpha=1[c];[v][c]overlay=0:0:shortest=1,fade=t=in:st=0:d=0.3,fade=t=out:st=2.5:d=0.3" \
  "${ENC[@]}" "$OUT/s5_ladder.mp4"

# --- 6. end card ---------------------------------------------------------
# The one card worth its seconds: it carries the name, the price and the URL.
say "end card"
ffmpeg -y -loglevel error -loop 1 -i "$FR/card_end.png" -t 2.6 \
  -vf "scale=$W:$H,fade=t=in:st=0:d=0.4,fade=t=out:st=2.1:d=0.5,format=yuv420p" \
  "${ENC[@]}" "$OUT/s6_end.mp4"

# --- 7. join -------------------------------------------------------------
# Hard cuts between shots, which is what an action promo wants; the fades are
# inside each segment above. concat demuxer needs identical codec params, and
# every segment above was encoded with the same ENC array for that reason.
say "joining"
: > "$OUT/list.txt"
for f in s0_cold s1_title s2_build s3_mach2 s4_fight s4b_light s4c_super s4d_heavy s5_ladder s6_end; do
  echo "file '$OUT/$f.mp4'" >> "$OUT/list.txt"
done
ffmpeg -y -loglevel error -f concat -safe 0 -i "$OUT/list.txt" -c copy "$OUT/promo_raw.mp4"

# Re-encode once at the end so the whole thing has a clean, seekable GOP
# structure and one consistent bitrate ladder.
ffmpeg -y -loglevel error -i "$OUT/promo_raw.mp4" "${ENC[@]}" -an "$OUT/promo.mp4"

# A 720p copy: the page picks it on a narrow screen, so a phone on cellular is
# not made to pull a 1080p file to play it in a 360px-wide box.
ffmpeg -y -loglevel error -i "$OUT/promo.mp4" -vf "scale=1280:720" \
  -c:v libx264 -preset slow -crf 22 -pix_fmt yuv420p -movflags +faststart -an "$OUT/promo_720.mp4"

# Poster: the frame the video sits on before anyone presses play, so it has to
# be the best frame in the film, not frame 0 (which is a fade from black).
ffmpeg -y -loglevel error -i "$FR/fight_0126.jpg" -vf "scale=$W:$H" -q:v 3 "$OUT/promo_poster.jpg"

# --- 8. music -------------------------------------------------------------
# ⚠ THE TRACK IS ONE OF THE GAME'S OWN FIGHT THEMES, and that matters twice:
# it is licensed for this project (owen), and it is what the game actually
# sounds like, so the promo is not promising a mood the product does not have.
# FightManager picks from three; ChromeWar is the one used here because it is
# the loudest of them with the least dynamic range (-14.25 LUFS, 2.7 LU), so it
# holds a steady bed under a fast cut instead of dropping out under a shot.
#
# Started at 92s, which is where the track's sustained energy peaks — measured
# per-frame RMS across all 153s rather than picked by ear.
#
# -14 LUFS is the level streaming platforms normalise to, so the film sits at
# the same loudness as everything else a viewer plays. A 0.6s fade in and a
# 1.6s fade out, because a promo that ends on a hard audio cut sounds broken.
MUSIC="${MUSIC:-$(cd "$(dirname "$0")/../.." && pwd)/Assets/Resources/FightTheme_ChromeWar.mp3}"
if [ -f "$MUSIC" ]; then
  DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/promo.mp4")
  say "music: $(basename "$MUSIC")"
  ffmpeg -y -loglevel error -i "$OUT/promo.mp4" -ss 92 -i "$MUSIC" \
    -filter_complex "[1:a]atrim=duration=$DUR,loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:st=0:d=0.6,afade=t=out:st=$(echo "$DUR-1.6" | bc):d=1.6[a]" \
    -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -ar 48000 -ac 2 -movflags +faststart -shortest "$OUT/promo_snd.mp4"
  mv "$OUT/promo_snd.mp4" "$OUT/promo.mp4"
  ffmpeg -y -loglevel error -i "$OUT/promo.mp4" -vf "scale=1280:720" \
    -c:v libx264 -preset slow -crf 22 -pix_fmt yuv420p -c:a aac -b:a 160k -ar 48000 -ac 2 \
    -movflags +faststart "$OUT/promo_720.mp4"
else
  echo "  NO MUSIC — $MUSIC not found; shipping silent"
fi

echo ""
echo "built:"
for f in promo.mp4 promo_720.mp4 promo_poster.jpg; do
  printf '  %-18s %s  %s\n' "$f" \
    "$(du -h "$OUT/$f" | cut -f1)" \
    "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/$f" 2>/dev/null | cut -c1-5)s"
done
