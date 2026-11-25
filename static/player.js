export function imageAt(durations, time) {
  let end = 0;
  for (let i = 0; i < durations.length; i++) {
    end += durations[i];
    if (time < end) return i;
  }
  return -1;
}
export async function mountPlayer(container, post) {
  const photos = post.media
    .filter((m) => m.kind === "image")
    .sort((a, b) => a.position - b.position);
  const length = photos.reduce((s, m) => s + m.seconds, 0);
  container.innerHTML = `<div class="player-stage"><img alt="Slideshow photo"><span class="player-overlay">Loading media…</span></div><div class="player-controls"><button class="play" aria-label="Play slideshow" disabled>▷</button><input class="seek" type="range" min="0" max="${length}" step="0.01" value="0" aria-label="Playback position"><span class="clock">0:00 / ${clock(length)}</span><span class="volume-label">Volume</span><input class="volume" type="range" min="0" max="1" step="0.05" value="1" aria-label="Playback volume"></div>`;
  const stage = container.querySelector(".player-stage"),
    image = stage.querySelector("img"),
    overlay = stage.querySelector(".player-overlay");
  const play = container.querySelector(".play"),
    seek = container.querySelector(".seek"),
    timeLabel = container.querySelector(".clock");
  let audio = null,
    urls = [],
    stopped = false,
    playing = false,
    elapsed = 0,
    started = 0,
    frame = 0,
    current = -2;
  const cleanup = () => {
    stopped = true;
    playing = false;
    cancelAnimationFrame(frame);
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    urls.forEach(URL.revokeObjectURL);
  };
  container.cleanup = cleanup;
  async function privateBlob(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw Error("Media is unavailable or access has changed.");
    const blob = URL.createObjectURL(await r.blob());
    if (stopped) {
      URL.revokeObjectURL(blob);
      throw Error("Player closed.");
    }
    urls.push(blob);
    return blob;
  }
  try {
    if (!photos.length)
      throw Error("Add and save at least one photo to preview.");
    const images = [];
    for (const p of photos) {
      const url = await privateBlob(p.url);
      await new Promise((resolve, reject) => {
        const i = new Image();
        i.onload = resolve;
        i.onerror = () => reject(Error("A photo could not load."));
        i.src = url;
      });
      images.push(url);
    }
    if (post.mix_url) {
      audio = new Audio(await privateBlob(post.mix_url));
      audio.preload = "auto";
      await new Promise((resolve, reject) => {
        audio.onloadedmetadata = resolve;
        audio.onerror = () => reject(Error("Audio could not load."));
      });
    }
    if (stopped) return cleanup();
    function render(t) {
      seek.value = Math.min(t, length);
      timeLabel.textContent = `${clock(t)} / ${clock(length)}`;
      const i = imageAt(
        photos.map((p) => p.seconds),
        t,
      );
      const visible = i < 0 ? photos.length - 1 : i;
      if (visible !== current) {
        current = visible;
        image.src = images[visible];
        image.alt = `Photo ${visible + 1} of ${photos.length}`;
      }
    }
    function pause() {
      elapsed = audio
        ? Math.min(audio.currentTime, length)
        : Math.min(elapsed + (performance.now() - started) / 1000, length);
      playing = false;
      if (audio) audio.pause();
      cancelAnimationFrame(frame);
      play.textContent = "▷";
      play.setAttribute("aria-label", "Play slideshow");
    }
    function tick() {
      if (!playing || stopped) return;
      const t = audio
        ? audio.currentTime
        : elapsed + (performance.now() - started) / 1000;
      render(t);
      if (t >= length - 0.005 || audio?.ended) {
        pause();
        elapsed = length;
        render(length);
        return;
      }
      frame = requestAnimationFrame(tick);
    }
    play.disabled = false;
    overlay.hidden = true;
    render(0);
    play.onclick = async () => {
      if (playing) {
        pause();
        return;
      }
      if (elapsed >= length - 0.01) {
        elapsed = 0;
        if (audio) audio.currentTime = 0;
      }
      try {
        if (audio) await audio.play();
        started = performance.now();
        playing = true;
        play.textContent = "Ⅱ";
        play.setAttribute("aria-label", "Pause slideshow");
        tick();
      } catch {
        overlay.hidden = false;
        overlay.textContent = "Playback failed. Close and reopen to retry.";
      }
    };
    seek.oninput = () => {
      elapsed = Number(seek.value);
      started = performance.now();
      if (audio) audio.currentTime = elapsed;
      render(elapsed);
    };
    container.querySelector(".volume").oninput = (e) => {
      if (audio) audio.volume = Number(e.target.value);
    };
  } catch (e) {
    if (stopped) return;
    overlay.textContent = e.message + " ";
    const retry = document.createElement("button");
    retry.className = "secondary";
    retry.textContent = "Retry";
    retry.onclick = () => {
      cleanup();
      mountPlayer(container, post);
    };
    overlay.appendChild(retry);
  }
  return cleanup;
}
function clock(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
