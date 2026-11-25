import { mountPlayer } from "./player.js";
const user = JSON.parse(document.body.dataset.user),
  main = document.getElementById("main");
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const path = location.pathname,
  id = Number(path.split("/").pop());
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let toastTimer;
function toast(message, error = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.toggle("error", error);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 6000);
}
async function api(url, method = "GET", data) {
  const options = {
    method,
    headers: { "X-CSRF-Token": csrf },
    cache: "no-store",
  };
  if (data !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(data);
  }
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      location.href = "/login";
    }
    throw Error(result.error || "The request failed. Try again.");
  }
  return result;
}
async function act(button, action) {
  if (button.disabled) return;
  button.disabled = true;
  try {
    await action();
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.disabled = false;
  }
}
const avatar = (name) =>
  `<span class="avatar">${esc(name?.slice(0, 1).toUpperCase() || "A")}</span>`;
const heading = (eyebrow, title, description, action = "") =>
  `<div class="heading-row"><div><span class="eyebrow">${eyebrow}</span><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
function empty(title, text, create = false) {
  return `<div class="empty-state"><div class="empty-icon">◉</div><h2>${title}</h2><p>${text}</p>${create ? '<button class="primary create-button-inline">Create a post</button>' : ""}</div>`;
}
async function createPost() {
  const result = await api("/api/posts", "POST", {});
  location.href = `/editor/${result.id}`;
}
document
  .querySelectorAll(".create-button")
  .forEach((b) => (b.onclick = () => act(b, createPost)));
document.getElementById("logout").onclick = (e) =>
  act(e.currentTarget, async () => {
    await api("/auth/logout", "POST", {});
    location.href = "/login";
  });
const nav = path.startsWith("/editor")
  ? "drafts"
  : path.startsWith("/profile")
    ? "profile"
    : path.startsWith("/post")
      ? "feed"
      : path.slice(1);
document.querySelector(`[data-nav="${nav}"]`)?.classList.add("active");
function wireCreate() {
  document
    .querySelectorAll(".create-button-inline")
    .forEach((b) => (b.onclick = () => act(b, createPost)));
}
async function confirmDelete(title, text) {
  const dialog = document.getElementById("confirm-dialog");
  document.getElementById("confirm-title").textContent = title;
  document.getElementById("confirm-text").textContent = text;
  dialog.showModal();
  return new Promise((resolve) => {
    document.getElementById("confirm-no").onclick = () => {
      dialog.close();
      resolve(false);
    };
    document.getElementById("confirm-yes").onclick = () => {
      dialog.close();
      resolve(true);
    };
    dialog.oncancel = () => resolve(false);
  });
}
function card(post) {
  const photos = post.media.filter((m) => m.kind === "image"),
    tracks = post.media.filter((m) => m.kind === "audio");
  const draft = post.state === "draft";
  const target = draft ? `/editor/${post.id}` : `/post/${post.id}`;
  return `<article class="post-card"><a class="post-image-link" href="${target}" aria-label="${draft ? "Edit draft" : "Open post"}: ${esc(post.caption || "Untitled moment")}">${photos.length ? `<img src="${photos[0].url}" loading="lazy" alt="Photo shared by ${esc(post.author)}">` : '<span class="empty-icon">＋</span>'}<span class="play-cover">▷</span><span class="image-overlay"><span class="media-badge">▧ ${photos.length}</span>${tracks.length ? `<span class="media-badge">♫ ${tracks.length}</span>` : ""}</span></a><div class="post-body"><div class="author-line"><a href="/profile/${post.owner_id}">${avatar(post.author)}</a><a href="/profile/${post.owner_id}"><strong>${esc(post.author)}</strong></a><span class="post-date">${new Date(post.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</span></div><a href="${target}"><p class="post-caption">${esc(post.caption || "Untitled moment")}</p></a><p class="post-location">⌖ &nbsp;${esc(post.location || "Ashoka University")}</p><div class="post-bottom">${draft ? `<a class="text-button" href="${target}">Continue editing ↗</a>` : `<button class="like-button ${post.liked ? "liked" : ""}" data-like="${post.id}" data-liked="${post.liked}"><span>${post.liked ? "♥" : "♡"}</span><b>${post.likes}</b></button>`}<span class="audience-label">${{ all: "◉ Campus", followers: "◎ Followers", groups: "▧ Circles", selected: "◈ Selected people" }[post.audience]}</span></div></div></article>`;
}
function wireLikes() {
  document.querySelectorAll("[data-like]").forEach(
    (b) =>
      (b.onclick = () =>
        act(b, async () => {
          const r = await api(
            `/api/posts/${b.dataset.like}/like`,
            b.dataset.liked === "true" ? "DELETE" : "PUT",
            {},
          );
          b.dataset.liked = String(r.liked);
          b.classList.toggle("liked", r.liked);
          b.innerHTML = `<span>${r.liked ? "♥" : "♡"}</span><b>${r.likes}</b>`;
        })),
  );
}
async function renderRail() {
  const rail = document.getElementById("rail");
  if (!rail) return;
  const [{ users }, { groups }] = await Promise.all([
    api("/api/users"),
    api("/api/groups"),
  ]);
  const people = users.filter((u) => u.id !== user.id).slice(0, 4);
  rail.innerHTML = `<section class="rail-block"><div class="rail-heading">Around your campus <a href="/people">View all ↗</a></div>${people.map((u) => `<div class="person-mini"><a href="/profile/${u.id}">${avatar(u.name)}</a><a href="/profile/${u.id}"><strong>${esc(u.name)}</strong><small>Campus member</small></a><button data-follow="${u.id}" data-following="${!!u.following}">${u.following ? "Following" : "＋ Follow"}</button></div>`).join("") || '<p class="help">Your classmates will appear here after signing in.</p>'}</section><section class="rail-block"><div class="rail-heading">Your circles <a href="/groups">Manage ↗</a></div>${
    groups
      .slice(0, 3)
      .map(
        (g) =>
          `<a href="/groups" class="circle-mini"><span>▧</span><div>${esc(g.name)}<small>${g.members.length} members</small></div></a>`,
      )
      .join("") ||
    '<p class="help">Create a circle to share with a smaller group.</p>'
  }</section><div class="rail-tip"><span class="eyebrow">A LITTLE INSPIRATION</span><p>A familiar corner. An unexpected sound. Your perspective makes it worth sharing.</p></div>`;
  wireFollows();
}
function wireFollows() {
  document.querySelectorAll("[data-follow]").forEach(
    (b) =>
      (b.onclick = () =>
        act(b, async () => {
          const following = b.dataset.following === "true";
          await api(
            `/api/users/${b.dataset.follow}/follow`,
            following ? "DELETE" : "PUT",
            {},
          );
          b.dataset.following = String(!following);
          b.textContent = following ? "＋ Follow" : "Following";
          toast(following ? "Unfollowed." : "Following.");
        })),
  );
}
async function feed() {
  const drafts = path === "/drafts";
  main.innerHTML =
    heading(
      drafts ? "YOUR WORKSPACE" : "THROUGH OUR LENS",
      drafts ? "A little work in progress." : "Life between the lectures.",
      drafts
        ? "Your private drafts, ready when you are."
        : "The sights, sounds and stories of our campus.",
      `<button class="primary create-button-inline">＋ Create a post</button>`,
    ) +
    (!drafts
      ? '<section class="hero-strip"><div><h2>Every moment has a point of view.</h2><p>A photo. A sound. A story only you can tell.</p></div><div class="hero-icon" aria-hidden="true">▧ ♫</div></section>'
      : "") +
    `<div class="content-layout"><section><div class="tabs-row"><div class="tabs">${drafts ? '<span class="tab active">Your drafts</span>' : '<button class="tab active" data-filter="campus">Campus</button><button class="tab" data-filter="following">Following</button>'}</div><span class="feed-count">NEWEST FIRST</span></div><div class="post-grid" id="posts"></div><button class="secondary load-more" id="more" hidden>Load more</button></section><aside class="right-rail" id="rail"></aside></div>`;
  wireCreate();
  let page = 0,
    following = false;
  async function load(append = false) {
    const result = await api(
      `/api/feed?page=${page}&drafts=${drafts ? 1 : 0}&following=${following ? 1 : 0}`,
    );
    const grid = document.getElementById("posts");
    if (!append) grid.innerHTML = "";
    grid.insertAdjacentHTML("beforeend", result.posts.map(card).join(""));
    if (!result.posts.length && !append)
      grid.innerHTML = empty(
        drafts
          ? "Your next story starts here."
          : following
            ? "A quieter corner of campus."
            : "Be the first to share a moment.",
        drafts
          ? "Create a post and save it here before publishing."
          : following
            ? "Follow people to see their shared posts here."
            : "Add photos, a little audio and your point of view.",
        !following,
      );
    document.getElementById("more").hidden = !result.more;
    wireLikes();
    wireCreate();
  }
  document.querySelectorAll("[data-filter]").forEach(
    (b) =>
      (b.onclick = () =>
        act(b, async () => {
          following = b.dataset.filter === "following";
          page = 0;
          document
            .querySelectorAll("[data-filter]")
            .forEach((t) => t.classList.toggle("active", t === b));
          await load();
        })),
  );
  document.getElementById("more").onclick = (e) =>
    act(e.currentTarget, async () => {
      page++;
      await load(true);
    });
  await load();
  await renderRail();
}
async function people() {
  main.innerHTML =
    heading(
      "THE PEOPLE BEHIND THE POSTS",
      "Familiar faces. New perspectives.",
      "Find your community and follow their campus stories.",
    ) +
    '<form class="search-box"><input aria-label="Search people" placeholder="Search by name or campus email"><button type="submit" class="text-button">Search ↗</button></form><div class="people-grid" id="people-list"></div>';
  async function load(q = "") {
    const { users } = await api("/api/users?q=" + encodeURIComponent(q));
    document.getElementById("people-list").innerHTML =
      users
        .map(
          (u) =>
            `<article class="person-card">${avatar(u.name)}<a href="/profile/${u.id}"><h3>${esc(u.name)}</h3></a><p>${esc(u.bio || u.email)}</p>${u.id === user.id ? '<a class="secondary" href="/profile/' + u.id + '">Your profile</a>' : `<button class="secondary" data-follow="${u.id}" data-following="${!!u.following}">${u.following ? "Following" : "＋ Follow"}</button>`}</article>`,
        )
        .join("") || empty("No matches.", "Try a different name or email.");
    wireFollows();
  }
  main.querySelector("form").onsubmit = (e) => {
    e.preventDefault();
    load(main.querySelector("input").value).catch((e) =>
      toast(e.message, true),
    );
  };
  await load();
}
async function profile() {
  const p = await api(`/api/users/${id}`),
    own = id === user.id;
  main.innerHTML = `<section class="profile-header"><span class="avatar large">${esc(p.name[0])}</span><div><span class="eyebrow">CAMPUS MEMBER</span><h1>${esc(p.name)}</h1><p>${esc(p.bio || "A different perspective on campus life.")}</p><div class="profile-stats"><span><strong>${p.followers}</strong> followers</span><span><strong>${p.following_count}</strong> following</span></div></div><div class="actions">${own ? '<button id="edit-profile" class="secondary">Edit profile</button>' : `<button class="secondary" data-follow="${id}" data-following="${p.following}">${p.following ? "Following" : "＋ Follow"}</button>`}</div></section><div id="profile-edit"></div><div class="tabs-row"><span class="tab active">Shared moments</span>${own ? '<a href="/drafts" class="text-button">View drafts ↗</a>' : ""}</div><div id="profile-posts" class="post-grid"></div><button class="secondary load-more" id="more" hidden>Load more</button>`;
  let page = 0;
  async function load() {
    const r = await api(`/api/feed?owner=${id}&page=${page}`);
    document
      .getElementById("profile-posts")
      .insertAdjacentHTML("beforeend", r.posts.map(card).join(""));
    if (page === 0 && !r.posts.length)
      document.getElementById("profile-posts").innerHTML = empty(
        "No shared moments here.",
        "Published posts shared with you will appear here.",
        own,
      );
    document.getElementById("more").hidden = !r.more;
    wireLikes();
    wireCreate();
  }
  document.getElementById("more").onclick = (e) =>
    act(e.currentTarget, async () => {
      page++;
      await load();
    });
  await load();
  wireFollows();
  if (own)
    document.getElementById("edit-profile").onclick = () => {
      document.getElementById("profile-edit").innerHTML =
        `<form class="panel"><h3>Edit profile</h3><label class="field">Display name<input name="name" maxlength="80" required value="${esc(p.name)}"></label><label class="field">Bio<textarea name="bio" maxlength="300">${esc(p.bio)}</textarea></label><p class="help">Your university email stays linked to your Google account.</p><div class="actions"><button type="submit" class="primary">Save profile</button></div></form>`;
      main.querySelector("form").onsubmit = (e) => {
        e.preventDefault();
        act(e.submitter, async () => {
          await api(
            "/api/profile",
            "PUT",
            Object.fromEntries(new FormData(e.target)),
          );
          location.reload();
        });
      };
    };
}
async function groups() {
  const { groups } = await api("/api/groups");
  main.innerHTML =
    heading(
      "A SMALLER AUDIENCE",
      "Keep your people close.",
      "Create circles for clubs, friends and the moments you share.",
    ) +
    '<form class="new-group"><input name="name" maxlength="60" required aria-label="New circle name" placeholder="Name your circle"><button class="primary" type="submit">＋ Create circle</button></form><div class="groups-grid">' +
    (groups
      .map(
        (g) =>
          `<article class="group-card"><div class="group-symbol">▧</div><h3>${esc(g.name)}</h3><p>${g.members.length} members · Created by ${esc(g.owner)}</p><div class="member-chips">${g.members.map((m) => `<span class="member-chip">${esc(m.name)}</span>`).join("")}</div>${
            g.owner_id === user.id
              ? `<form data-group="${g.id}"><label class="field">Member emails<textarea name="emails" placeholder="One campus email per line">${esc(
                  g.members
                    .filter((m) => m.id !== user.id)
                    .map((m) => m.email)
                    .join("\n"),
                )}</textarea></label><p class="help">Members must have signed in to Ashoka Lens. You stay in your circle.</p><div class="actions"><button class="secondary" type="submit">Save members</button><button class="text-button" type="button" data-delete-group="${g.id}">Delete</button></div></form>`
              : '<p class="help">The circle owner manages membership.</p>'
          }</article>`,
      )
      .join("") ||
      empty(
        "Your circles start here.",
        "Give your group a name to start sharing together.",
      )) +
    "</div>";
  main.querySelector(".new-group").onsubmit = (e) => {
    e.preventDefault();
    act(e.submitter, async () => {
      await api("/api/groups", "POST", { name: e.target.elements.name.value });
      location.reload();
    });
  };
  main.querySelectorAll("[data-group]").forEach(
    (f) =>
      (f.onsubmit = (e) => {
        e.preventDefault();
        act(e.submitter, async () => {
          await api(`/api/groups/${f.dataset.group}`, "PUT", {
            emails: splitEmails(f.elements.emails.value),
          });
          toast("Circle members updated.");
          location.reload();
        });
      }),
  );
  main.querySelectorAll("[data-delete-group]").forEach(
    (b) =>
      (b.onclick = () =>
        act(b, async () => {
          if (
            await confirmDelete(
              "Delete this circle?",
              "Posts shared only through this circle will no longer be visible to its members.",
            )
          ) {
            await api(`/api/groups/${b.dataset.deleteGroup}`, "DELETE");
            location.reload();
          }
        })),
  );
}
function splitEmails(text) {
  return [
    ...new Set(
      text
        .split(/[\s,;]+/)
        .map((x) => x.trim().toLowerCase())
        .filter(Boolean),
    ),
  ];
}
async function postView() {
  const post = await api(`/api/posts/${id}`);
  main.innerHTML = `<section class="post-view">${heading("A CAMPUS MOMENT", esc(post.caption || "Through the lens"), esc(post.location || "Ashoka University"))}<div class="author-line"><a href="/profile/${post.owner_id}">${avatar(post.author)} <strong>${esc(post.author)}</strong></a><span class="audience-label">${esc({ all: "Campus", followers: "Followers", groups: "Circles", selected: "Selected people" }[post.audience])}</span></div><div id="post-player" style="margin-top:20px"></div><div class="post-tools"><button class="like-button ${post.liked ? "liked" : ""}" data-like="${id}" data-liked="${post.liked}"><span>${post.liked ? "♥" : "♡"}</span><b>${post.likes}</b></button>${post.owner_id === user.id ? `<a class="secondary" href="/editor/${id}">Edit post</a><button class="danger" id="delete-post">Delete</button>` : ""}<a href="/feed" class="text-button">Back to feed ↗</a></div></section>`;
  await mountPlayer(document.getElementById("post-player"), post);
  wireLikes();
  document.getElementById("delete-post")?.addEventListener("click", (e) =>
    act(e.currentTarget, async () => {
      if (
        await confirmDelete(
          "Delete this post?",
          "The post and all its original and edited files will be removed.",
        )
      ) {
        await api(`/api/posts/${id}`, "DELETE");
        location.href = "/feed";
      }
    }),
  );
}
async function editor() {
  let post = await api(`/api/posts/${id}?edit=1`);
  if (post.owner_id !== user.id)
    throw Error("Only the owner can edit this post.");
  const [{ locations }, { groups }] = await Promise.all([
    api("/api/me"),
    api("/api/groups"),
  ]);
  let selected = post.media.map((m) => ({ ...m }));
  if (!selected.length && post.state === "draft") {
    for (const source of post.originals) {
      const candidate = post.candidates
        .filter((c) => c.source_id === source.id)
        .pop();
      if (candidate) selected.push({ ...candidate });
    }
  }
  let busy = false;
  main.innerHTML =
    heading(
      "YOUR PERSPECTIVE",
      post.state === "published"
        ? "Refine your moment."
        : "Make a moment yours.",
      "Photos, sound and a little creative freedom.",
      `<a class="text-button" href="/drafts">← Your drafts</a>`,
    ) +
    `<div class="editor-layout"><div><section class="panel"><div class="panel-title"><span class="step">01</span><h2>Your media</h2><small>10 photos · 3 audio clips</small></div><label class="upload-zone" id="drop-zone"><span>＋</span><strong>Drop your moments here</strong><small>or choose photos and audio from your device</small><input id="upload" type="file" multiple accept="image/jpeg,image/png,audio/mpeg,audio/wav,.mp3,.wav" aria-label="Upload photos and audio"></label><div class="file-limits"><span>JPG / PNG · 10 MB each</span><span>MP3 / WAV · 20 MB each</span><span>100 MB total</span></div><progress class="upload-progress" id="upload-progress" max="100" value="0" hidden></progress><p id="work-status" role="status" class="save-status" style="margin-top:12px"></p><div id="media-editors" class="media-editor-list"></div><div class="duration-total"><span>Slideshow duration</span><strong id="total-duration">0 / 60 seconds</strong></div><p class="help">Audio clips start together and are mixed at equal weight. Short clips leave silence; the soundtrack ends with your slideshow.</p></section><section class="panel"><div class="panel-title"><span class="step">02</span><h2>Preview your story</h2></div><p class="help">Save your draft or changes to preview the latest composition.</p><button id="preview" class="secondary" style="margin-top:15px">▷ Preview saved post</button></section><details class="retry-jobs panel"><summary>Processing history</summary><div id="job-list"></div></details></div><div><section class="panel"><div class="panel-title"><span class="step">03</span><h2>The story behind it</h2></div><label class="field">Caption<textarea id="caption" maxlength="1000" placeholder="What’s the story?">${esc(post.caption)}</textarea></label><label class="field">Campus location<select id="location"><option value="">Choose a campus spot</option>${locations.map((l) => `<option value="${l.id}" ${l.id === post.location_id ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select></label></section><section class="panel"><div class="panel-title"><span class="step">04</span><h2>Who’s this moment for?</h2></div><label class="field">Audience<select id="audience">${Object.entries(
      {
        all: "Everyone on campus",
        followers: "My followers",
        groups: "My circles",
        selected: "Selected people",
      },
    )
      .map(
        ([v, t]) =>
          `<option value="${v}" ${v === post.audience ? "selected" : ""}>${t}</option>`,
      )
      .join(
        "",
      )}</select></label><div id="audience-extra"></div><p class="help">Only signed-in, verified Ashoka members can view your posts. Drafts and originals stay private.</p></section><section class="panel"><p class="save-status" id="save-status">${post.state === "draft" ? "Private draft" : "Published post"} · Revision ${post.revision}</p><div class="actions"><button class="secondary" id="save">${post.state === "published" ? "Save changes" : "Save draft"}</button><button class="primary" id="publish">${post.state === "published" ? "Save & view" : "Publish moment"} ↗</button></div><p class="inline-error" id="editor-error" role="alert"></p></section></div></div>`;
  const setStatus = (t) =>
    (document.getElementById("work-status").textContent = t);
  function audienceExtra() {
    const value = document.getElementById("audience").value,
      el = document.getElementById("audience-extra");
    el.innerHTML =
      value === "selected"
        ? `<label class="field">Campus email addresses<textarea id="recipients" placeholder="One email per line">${esc(post.viewers.map((v) => v.email).join("\n"))}</textarea></label><p class="help">Recipients must have signed in before. An empty list keeps the post owner-only.</p>`
        : value === "groups"
          ? `<div class="group-checks">${
              groups
                .filter((g) => g.owner_id === user.id)
                .map(
                  (g) =>
                    `<label><input type="checkbox" value="${g.id}" ${post.group_ids.includes(g.id) ? "checked" : ""}>${esc(g.name)}</label>`,
                )
                .join("") ||
              '<p class="help">Create a circle in Your circles first.</p>'
            }</div><p class="help">Current circle membership determines access.</p>`
          : "";
  }
  document.getElementById("audience").onchange = audienceExtra;
  audienceExtra();
  function total() {
    document.getElementById("total-duration").textContent = `${selected
      .filter((m) => m.kind === "image")
      .reduce((s, m) => s + Number(m.seconds), 0)
      .toFixed(1)} / 60 seconds`;
  }
  function renderMedia() {
    document.getElementById("media-editors").innerHTML =
      selected
        .map((m, index) => {
          const source = post.originals.find((s) => s.id === m.source_id),
            meta = source.metadata,
            settings = m.settings;
          return `<article class="media-editor" data-index="${index}"><div class="media-editor-head">${m.kind === "image" ? `<img src="${m.url}" alt="Photo ${index + 1} preview">` : '<span class="avatar">♫</span>'}<div><strong>${esc(source.filename)}</strong><small>${m.kind === "image" ? `${meta.width} × ${meta.height} pixels` : `${meta.duration.toFixed(1)} seconds`} · ${m.kind}</small></div><div class="file-actions"><button class="icon-button move-up" aria-label="Move media up">↑</button><button class="icon-button move-down" aria-label="Move media down">↓</button><button class="icon-button remove-media" aria-label="Remove media">×</button></div></div><div style="padding:0 13px">${m.kind === "image" ? `<label class="duration-line">Show for <input class="seconds" type="number" min="0.1" max="60" step="0.1" value="${m.seconds}"> seconds</label>` : `<audio controls preload="none" src="${m.url}"></audio>`}</div><details><summary>${m.kind === "image" ? "Crop, rotate & adjust" : "Trim & volume"}</summary><form class="edit-form">${m.kind === "image" ? `<div class="form-grid"><label>Rotate clockwise<select name="rotate">${[0, 90, 180, 270].map((a) => `<option value="${a}" ${a === (settings.rotate || 0) ? "selected" : ""}>${a}°</option>`).join("")}</select></label><label>Filter<select name="filter">${["none", "greyscale", "warm", "cool"].map((f) => `<option ${f === (settings.filter || "none") ? "selected" : ""}>${f}</option>`).join("")}</select></label><label>Brightness<input type="number" name="brightness" min="0.2" max="2" step="0.1" value="${settings.brightness ?? 1}"></label><label>Contrast<input type="number" name="contrast" min="0.2" max="2" step="0.1" value="${settings.contrast ?? 1}"></label><div class="full"><label>Crop bounds in original pixels</label><div class="crop-grid">${["Left", "Top", "Right", "Bottom"].map((t, i) => `<label>${t}<input type="number" name="crop${i}" min="0" value="${settings.crop?.[i] ?? [0, 0, meta.width, meta.height][i]}"></label>`).join("")}</div></div><label>Resize width<input type="number" name="width" min="1" max="10000" value="${settings.size?.[0] || ""}" placeholder="Keep size"></label><label>Resize height<input type="number" name="height" min="1" max="10000" value="${settings.size?.[1] || ""}" placeholder="Keep size"></label></div>` : `<div class="form-grid"><label>Start (seconds)<input type="number" name="start" min="0" step="0.01" value="${settings.start ?? 0}"></label><label>End (seconds)<input type="number" name="end" min="0" step="0.01" max="${meta.duration}" value="${settings.end ?? meta.duration}"></label><label>Volume (0–1)<input type="number" name="volume" min="0" max="1" step="0.05" value="${settings.volume ?? 1}"></label></div>`}<div class="actions"><button type="submit" class="secondary">Apply edit</button><button type="button" class="text-button reset-edit">Reset to original</button></div><p class="help">Edits are made from your preserved original. Save the post to apply them to the published version.</p></form></details></article>`;
        })
        .join("") ||
      '<p class="help">Your uploaded photos and audio will appear here.</p>';
    document.querySelectorAll(".media-editor").forEach((el) => {
      const index = Number(el.dataset.index);
      el.querySelector(".seconds")?.addEventListener("input", (e) => {
        selected[index].seconds = Number(e.target.value);
        total();
      });
      el.querySelector(".remove-media").onclick = () => {
        if (busy) return;
        selected.splice(index, 1);
        renderMedia();
      };
      for (const [selector, delta] of [
        [".move-up", -1],
        [".move-down", 1],
      ])
        el.querySelector(selector).onclick = () => {
          if (busy) return;
          const next = index + delta;
          if (next >= 0 && next < selected.length) {
            [selected[index], selected[next]] = [
              selected[next],
              selected[index],
            ];
            renderMedia();
          }
        };
      const form = el.querySelector("form");
      form.onsubmit = (e) => {
        e.preventDefault();
        const v = Object.fromEntries(new FormData(form));
        let settings;
        if (selected[index].kind === "image") {
          if (Boolean(v.width) !== Boolean(v.height)) {
            toast("Enter both resize dimensions, or leave both blank.", true);
            return;
          }
          settings = {
            rotate: Number(v.rotate),
            filter: v.filter,
            brightness: Number(v.brightness),
            contrast: Number(v.contrast),
            crop: [0, 1, 2, 3].map((i) => Number(v["crop" + i])),
            size:
              v.width && v.height ? [Number(v.width), Number(v.height)] : null,
          };
        } else
          settings = {
            start: Number(v.start),
            end: Number(v.end),
            volume: Number(v.volume),
          };
        applyEdit(index, settings);
      };
      el.querySelector(".reset-edit").onclick = () => applyEdit(index, {});
    });
    total();
  }
  async function work(action) {
    if (busy) return;
    busy = true;
    document.getElementById("editor-error").textContent = "";
    main
      .querySelectorAll("button,input[type=file]")
      .forEach((b) => (b.disabled = true));
    try {
      await action();
    } catch (e) {
      document.getElementById("editor-error").textContent = e.message;
      toast(e.message, true);
    } finally {
      busy = false;
      main
        .querySelectorAll("button,input[type=file]")
        .forEach((b) => (b.disabled = false));
      setStatus("");
    }
  }
  async function applyEdit(index, settings) {
    await work(async () => {
      setStatus("Preparing your edited copy…");
      const m = selected[index],
        out = await api(
          `/api/posts/${id}/media/${m.source_id}/edits`,
          "POST",
          settings,
        );
      selected[index] = { ...out, seconds: m.seconds };
      renderMedia();
      toast("Edit ready. Save the post to keep this composition.");
    });
  }
  function uploadOne(file) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest(),
        data = new FormData();
      data.append("file", file);
      data.append("revision", post.revision);
      xhr.open("POST", `/api/posts/${id}/media`);
      xhr.setRequestHeader("X-CSRF-Token", csrf);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable)
          document.getElementById("upload-progress").value =
            (e.loaded / e.total) * 100;
      };
      xhr.onload = () => {
        try {
          const r = JSON.parse(xhr.responseText);
          xhr.status < 300 ? resolve(r) : reject(Error(r.error));
        } catch {
          reject(Error("Upload failed. Please retry."));
        }
      };
      xhr.onerror = () =>
        reject(Error("Connection interrupted. Reload to recover saved media."));
      xhr.timeout = 180000;
      xhr.ontimeout = () =>
        reject(Error("Upload timed out. Reload to recover saved media."));
      xhr.send(data);
    });
  }
  async function uploadFiles(files) {
    await work(async () => {
      document.getElementById("upload-progress").hidden = false;
      try {
        for (const [i, file] of [...files].entries()) {
          setStatus(`Uploading ${i + 1} of ${files.length}: ${file.name}`);
          const result = await uploadOne(file);
          post.revision = result.revision;
          post.originals.push(result.original);
          selected.push(result.output);
          renderMedia();
        }
        toast("Media added. Set your timing and sharing.");
      } finally {
        document.getElementById("upload-progress").hidden = true;
        document.getElementById("upload").value = "";
      }
    });
  }
  document.getElementById("upload").onchange = (e) =>
    uploadFiles(e.target.files);
  const zone = document.getElementById("drop-zone");
  zone.ondragover = (e) => {
    e.preventDefault();
    zone.classList.add("dragover");
  };
  zone.ondragleave = () => zone.classList.remove("dragover");
  zone.ondrop = (e) => {
    e.preventDefault();
    zone.classList.remove("dragover");
    uploadFiles(e.dataTransfer.files);
  };
  async function save(publish) {
    await work(async () => {
      setStatus("Saving your composition…");
      const data = {
        revision: post.revision,
        caption: document.getElementById("caption").value,
        location_id: Number(document.getElementById("location").value) || null,
        audience: document.getElementById("audience").value,
        emails: splitEmails(document.getElementById("recipients")?.value || ""),
        group_ids: [
          ...document.querySelectorAll(".group-checks input:checked"),
        ].map((c) => Number(c.value)),
        media: selected.map((m) => ({ id: m.id, seconds: m.seconds })),
        publish,
      };
      post = await api(`/api/posts/${id}`, "PUT", data);
      selected = post.media.map((m) => ({ ...m }));
      document.getElementById("save-status").textContent =
        `${post.state === "published" ? "Published post" : "Private draft"} · Saved`;
      renderMedia();
      toast("Your moment is saved.");
      if (publish) location.href = `/post/${id}`;
    });
  }
  document.getElementById("save").onclick = () => save(false);
  document.getElementById("publish").onclick = () => save(true);
  document.getElementById("preview").onclick = async () => {
    const dialog = document.getElementById("player-dialog");
    dialog.showModal();
    const container = document.getElementById("player-content");
    await mountPlayer(container, post);
  };
  const dialog = document.getElementById("player-dialog");
  dialog.querySelector(".close-player").onclick = () => dialog.close();
  dialog.onclose = () => document.getElementById("player-content").cleanup?.();
  document.getElementById("job-list").innerHTML =
    post.jobs
      .map(
        (j) =>
          `<div class="retry-job"><span>${esc(j.kind)} · ${esc(j.state)}${j.error ? " · " + esc(j.error) : ""}</span>${j.state === "Failed" && j.input_id ? `<button class="secondary" data-retry="${j.id}">Retry</button>` : ""}</div>`,
      )
      .join("") || '<p class="help">Upload a file to begin.</p>';
  document.querySelectorAll("[data-retry]").forEach(
    (b) =>
      (b.onclick = () =>
        work(async () => {
          const out = await api(
            `/api/posts/${id}/jobs/${b.dataset.retry}/retry`,
            "POST",
            {},
          );
          const index = selected.findIndex(
            (m) => m.source_id === out.source_id,
          );
          if (index < 0) selected.push(out);
          else selected[index] = { ...out, seconds: selected[index].seconds };
          renderMedia();
          toast("Retry succeeded. Save the post to keep the result.");
        })),
  );
  renderMedia();
}
const route =
  path === "/feed" || path === "/drafts"
    ? feed
    : path === "/people"
      ? people
      : path === "/groups"
        ? groups
        : path.startsWith("/profile")
          ? profile
          : path.startsWith("/editor")
            ? editor
            : postView;
route().catch((e) => {
  main.innerHTML = `<section class="error-panel"><h2>We couldn’t open this page.</h2><p>${esc(e.message)}</p><a class="secondary" href="/feed">Back to campus</a></section>`;
});
