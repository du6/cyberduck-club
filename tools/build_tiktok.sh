#!/bin/bash
# build_tiktok.sh - cut the TikTok promo (1080x1920, 30 fps) from captured frames.
# Same rules as website/tools/build_promo.sh: this ffmpeg has NO drawtext (all
# words are canvas PNGs), captions need -loop 1 + overlay=shortest=1, yuv420p.
set -euo pipefail
FR=/tmp/tiktok_frames; OUT=/tmp/tiktok_out; mkdir -p "$OUT"
MUSIC="/Users/leondu/Setup Guide In-Editor Tutorial/_claude_backups/phoneload_mp3/FightTheme_ChromeWar.mp3"
W=1080; H=1920; FPS=30
ENC=(-c:v libx264 -preset slow -crf 21 -pix_fmt yuv420p -movflags +faststart -r $FPS)
say(){ printf '  %s\n' "$1"; }
# caption chain: 9:16 footage under a PNG that fades in
cap(){ echo "[0:v]scale=$W:$H,setsar=1[v];[1:v]scale=$W:$H,format=rgba,fps=$FPS,fade=t=in:st=$1:d=0.35:alpha=1[c];[v][c]overlay=0:0:shortest=1$2"; }

say "0 cold open: the hit (slight slow-mo) + hook"
# ⚠ -t, NOT -frames:v: -frames:v counts OUTPUT frames at 30 fps, so 70 cut this
# 24 fps shot at 2.33 s - before its own fade-out (measured 2026-09-04).
ffmpeg -y -loglevel error -framerate 24 -start_number 20 -i "$FR/fightA_%04d.jpg" -loop 1 -i "$FR/cap_hook.png" -t 2.9 \
  -filter_complex "$(cap 0.25 ',fade=t=out:st=2.65:d=0.25')" "${ENC[@]}" "$OUT/s0.mp4"

say "1 the machine, turning + build caption"
ffmpeg -y -loglevel error -framerate $FPS -i "$FR/turn_%04d.jpg" -loop 1 -i "$FR/cap_build.png" -frames:v 75 \
  -filter_complex "$(cap 0.2 ',fade=t=in:st=0:d=0.25,fade=t=out:st=2.25:d=0.25')" "${ENC[@]}" "$OUT/s1.mp4"

say "2 second fight + win/loss caption"
ffmpeg -y -loglevel error -framerate $FPS -i "$FR/fightC_%04d.jpg" -loop 1 -i "$FR/cap_loss.png" -frames:v 105 \
  -filter_complex "$(cap 0.2 ',fade=t=in:st=0:d=0.25,fade=t=out:st=3.25:d=0.25')" "${ENC[@]}" "$OUT/s2.mp4"

say "3 third fight, link only"
ffmpeg -y -loglevel error -framerate $FPS -i "$FR/fightD_%04d.jpg" -loop 1 -i "$FR/cap_link.png" -frames:v 80 \
  -filter_complex "$(cap 0.0 ',fade=t=in:st=0:d=0.25,fade=t=out:st=2.4:d=0.27')" "${ENC[@]}" "$OUT/s3.mp4"

say "4 the workshop: SCRAPPER waiting (centre crop, slow push) + ready caption"
ffmpeg -y -loglevel error -loop 1 -i "$FR/unity_workshop.jpg" -loop 1 -i "$FR/cap_ready.png" -t 3 \
  -filter_complex "[0:v]crop=600:1067:'(iw-600)/2':170,scale=1296:2304,zoompan=z='min(zoom+0.0009,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=90:s=${W}x${H}:fps=$FPS,setsar=1[v];[1:v]scale=$W:$H,format=rgba,fps=$FPS,fade=t=in:st=0.3:d=0.35:alpha=1[c];[v][c]overlay=0:0:shortest=1,fade=t=in:st=0:d=0.25,fade=t=out:st=2.75:d=0.25" \
  "${ENC[@]}" "$OUT/s4.mp4"

say "5 end card"
ffmpeg -y -loglevel error -loop 1 -i "$FR/card_end.png" -t 3.2 \
  -vf "scale=$W:$H,fade=t=in:st=0:d=0.3,format=yuv420p" "${ENC[@]}" "$OUT/s5.mp4"

say "concat + music"
printf "file '%s'\n" "$OUT"/s0.mp4 "$OUT"/s1.mp4 "$OUT"/s2.mp4 "$OUT"/s3.mp4 "$OUT"/s4.mp4 "$OUT"/s5.mp4 > "$OUT/list.txt"
# ⚠ JOIN WITH THE CONCAT FILTER, NOT THE DEMUXER. The demuxer (even re-encoding)
# decoded every join dark for ~1 s - image-born cards and frame sequences carry
# different parameter sets. Decoding every segment and encoding once is clean;
# an every-frame YAVG scan then showed dark frames only inside the fades.
ffmpeg -y -loglevel error -i "$OUT/s0.mp4" -i "$OUT/s1.mp4" -i "$OUT/s2.mp4" -i "$OUT/s3.mp4" -i "$OUT/s4.mp4" -i "$OUT/s5.mp4" \
  -filter_complex "[0:v][1:v][2:v][3:v][4:v][5:v]concat=n=6:v=1:a=0,format=yuv420p[v]" -map "[v]" \
  -c:v libx264 -preset slow -crf 21 -r $FPS -movflags +faststart "$OUT/silent.mp4"
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/silent.mp4")
ffmpeg -y -loglevel error -i "$OUT/silent.mp4" -ss 0 -i "$MUSIC" -filter_complex "[1:a]atrim=0:$DUR,afade=t=in:st=0:d=0.3,afade=t=out:st=$(echo "$DUR-1.6" | bc):d=1.6,volume=0.9[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 160k -shortest "$OUT/robot-brawl-tiktok.mp4"
say "done: $OUT/robot-brawl-tiktok.mp4 ($DUR s)"
