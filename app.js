let csrfToken = "";
let currentUser = null;
let socket = null;
let localStream = null;
let screenStream = null;
let peerConnections = {};
let pendingCandidates = {};
let peerNames = {};
let activeRoomId = null;
let iceServers = [{ urls: "stun:stun.l.google.com:19302" }];
let resetToken = null;

/* -------------------------------------------------------
   API HELPER
------------------------------------------------------- */
async function api(url, options = {}) {
    options.headers = options.headers || {};
    options.headers["Content-Type"] = "application/json";
    if (options.method && options.method !== "GET") {
        options.headers["X-CSRF-Token"] = csrfToken;
    }
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || "Something went wrong.");
    }
    return data;
}

/* -------------------------------------------------------
   INIT
------------------------------------------------------- */
async function initialise() {
    // Check for password reset token in hash
    const hash = location.hash || "";
    if (hash.startsWith("#reset=")) {
        resetToken = hash.slice(7);
        showAuth("reset");
        document.getElementById("authScreen").classList.remove("hidden");
        return;
    }

    const csrf = await fetch("/api/csrf");
    const csrfData = await csrf.json();
    csrfToken = csrfData.csrf_token;

    try {
        currentUser = await api("/api/me");
        showApplication();
        await loadFeed();
        loadNotifications();
    } catch {
        showAuthScreen();
    }
}

function showAuthScreen() {
    document.getElementById("authScreen").classList.remove("hidden");
    document.getElementById("app").classList.add("hidden");
}

function showApplication() {
    document.getElementById("authScreen").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");
    populateProfile();
    connectSocket();
    // restore theme
    if (localStorage.getItem("theme") === "dark") {
        document.body.classList.add("dark");
    }
}

/* -------------------------------------------------------
   AUTH
------------------------------------------------------- */
function showAuth(type) {
    ["loginForm", "registerForm", "forgotForm", "resetForm"].forEach(id => {
        document.getElementById(id).classList.add("hidden");
    });
    document.getElementById("loginTab").classList.remove("active");
    document.getElementById("registerTab").classList.remove("active");

    if (type === "login") {
        document.getElementById("loginForm").classList.remove("hidden");
        document.getElementById("loginTab").classList.add("active");
    } else if (type === "register") {
        document.getElementById("registerForm").classList.remove("hidden");
        document.getElementById("registerTab").classList.add("active");
    } else if (type === "forgot") {
        document.getElementById("forgotForm").classList.remove("hidden");
    } else if (type === "reset") {
        document.getElementById("resetForm").classList.remove("hidden");
    }
}

document.getElementById("loginForm").addEventListener("submit", async e => {
    e.preventDefault();
    const message = document.getElementById("authMessage");
    try {
        await api("/api/login", {
            method: "POST",
            body: JSON.stringify({
                email: document.getElementById("loginEmail").value,
                password: document.getElementById("loginPassword").value
            })
        });
        currentUser = await api("/api/me");
        showApplication();
        await loadFeed();
        loadNotifications();
    } catch (err) {
        message.textContent = err.message;
    }
});

document.getElementById("registerForm").addEventListener("submit", async e => {
    e.preventDefault();
    const message = document.getElementById("authMessage");
    try {
        await api("/api/register", {
            method: "POST",
            body: JSON.stringify({
                name: document.getElementById("registerName").value,
                student_number: document.getElementById("registerStudentNumber").value,
                email: document.getElementById("registerEmail").value,
                password: document.getElementById("registerPassword").value,
                faculty: document.getElementById("registerFaculty").value,
                course: document.getElementById("registerCourse").value
            })
        });
        message.textContent = "Account created. Check your SFU email to verify.";
        message.style.color = "var(--success)";
        showAuth("login");
    } catch (err) {
        message.textContent = err.message;
        message.style.color = "var(--danger)";
    }
});

document.getElementById("forgotForm").addEventListener("submit", async e => {
    e.preventDefault();
    const message = document.getElementById("authMessage");
    try {
        await api("/api/forgot-password", {
            method: "POST",
            body: JSON.stringify({ email: document.getElementById("forgotEmail").value })
        });
        message.textContent = "If that email exists, a reset link has been sent.";
        message.style.color = "var(--success)";
    } catch (err) {
        message.textContent = err.message;
    }
});

document.getElementById("resetForm").addEventListener("submit", async e => {
    e.preventDefault();
    const message = document.getElementById("authMessage");
    try {
        await api("/api/reset-password", {
            method: "POST",
            body: JSON.stringify({
                token: resetToken,
                password: document.getElementById("resetPassword").value
            })
        });
        message.textContent = "Password updated. You can log in.";
        message.style.color = "var(--success)";
        location.hash = "";
        showAuth("login");
    } catch (err) {
        message.textContent = err.message;
    }
});

async function logout() {
    try { await api("/api/logout", { method: "POST" }); } catch {}
    if (socket) socket.disconnect();
    location.reload();
}

/* -------------------------------------------------------
   NAVIGATION
------------------------------------------------------- */
function showPage(page) {
    document.querySelectorAll(".page").forEach(el => el.classList.add("hidden"));
    const selected = document.getElementById(`${page}Page`);
    if (selected) selected.classList.remove("hidden");

    if (page === "home") loadFeed();
    if (page === "discover") loadAroundMe();
    if (page === "people") loadPeople();
    if (page === "groups") loadGroups();
    if (page === "projects") loadProjects();
    if (page === "skills") loadSkillExchanges();
    if (page === "rooms") loadRooms();
    if (page === "portfolio") populateProfile();
    if (page === "ai") {} // already static
}

function toggleDark() {
    document.body.classList.toggle("dark");
    localStorage.setItem("theme", document.body.classList.contains("dark") ? "dark" : "light");
}

/* -------------------------------------------------------
   FEED
------------------------------------------------------- */
async function loadFeed() {
    try {
        const feed = await api("/api/feed");
        const container = document.getElementById("feed");
        container.innerHTML = "";
        if (!feed.length) {
            container.innerHTML = "<p>No posts yet. Be the first!</p>";
            return;
        }
        feed.forEach(item => {
            const el = document.createElement("div");
            el.className = "feed-item";
            el.innerHTML = `
                <div class="feed-header">
                    <div class="avatar">${escapeHtml(item.name.charAt(0).toUpperCase())}</div>
                    <div>
                        <strong>${escapeHtml(item.name)}</strong>
                        <small> · ${escapeHtml(item.faculty || "")}</small>
                    </div>
                </div>
                <p>${escapeHtml(item.body)}</p>
                ${item.achievement ? '<span class="achievement">🏆 Achievement</span>' : ""}
            `;
            container.appendChild(el);
        });
    } catch (err) {
        console.error(err);
    }
}

async function postStatus() {
    const text = document.getElementById("statusText");
    const achievement = document.getElementById("achievementCheck");
    if (!text.value.trim()) return;
    try {
        await api("/api/status", {
            method: "POST",
            body: JSON.stringify({ body: text.value, achievement: achievement.checked })
        });
        text.value = "";
        achievement.checked = false;
        await loadFeed();
    } catch (err) {
        alert(err.message);
    }
}

/* -------------------------------------------------------
   AROUND ME + PEOPLE
------------------------------------------------------- */
function shareLocation() {
    if (!navigator.geolocation) {
        alert("Geolocation is not supported.");
        return;
    }
    navigator.geolocation.getCurrentPosition(async pos => {
        try {
            await api("/api/location", {
                method: "POST",
                body: JSON.stringify({
                    latitude: pos.coords.latitude,
                    longitude: pos.coords.longitude
                })
            });
            await loadAroundMe();
        } catch (err) {
            alert(err.message);
        }
    }, () => alert("Location permission was not granted."), {
        enableHighAccuracy: false,
        maximumAge: 300000,
        timeout: 10000
    });
}

async function loadAroundMe() {
    const container = document.getElementById("aroundMe");
    try {
        const data = await api("/api/around-me?radius_km=10");
        container.innerHTML = "";

        if (data.mentors.length) {
            const h = document.createElement("h3");
            h.textContent = "Nearby mentors";
            container.appendChild(h);
            data.mentors.forEach(m => {
                const card = document.createElement("div");
                card.className = "around-card";
                card.innerHTML = `
                    <div class="avatar">${escapeHtml(m.name.charAt(0).toUpperCase())}</div>
                    <h3>${escapeHtml(m.name)} ${m.identity_verified ? "✓" : ""}</h3>
                    <p>${escapeHtml(m.headline || m.faculty || "")}</p>
                    <p class="skills">${escapeHtml(m.skills || "")}</p>
                    <p class="distance">📍 ${m.distance_km} km</p>
                    <button class="small-button" onclick="reportUser(${m.id})">Report</button>
                `;
                container.appendChild(card);
            });
        }

        if (data.active_rooms.length) {
            const h = document.createElement("h3");
            h.textContent = "Active study rooms";
            container.appendChild(h);
            data.active_rooms.forEach(r => {
                const card = document.createElement("div");
                card.className = "around-card";
                card.innerHTML = `
                    <h3>🎥 ${escapeHtml(r.name)}</h3>
                    <p>${escapeHtml(r.group_name)}</p>
                    <button class="primary-button" onclick="openVideoRoom(${r.id}, '${escapeJs(r.name)}')">Join</button>
                `;
                container.appendChild(card);
            });
        }

        if (data.projects.length) {
            const h = document.createElement("h3");
            h.textContent = "Open projects nearby";
            container.appendChild(h);
            data.projects.forEach(p => {
                const card = document.createElement("div");
                card.className = "around-card";
                card.innerHTML = `
                    <h3>${escapeHtml(p.title)}</h3>
                    <p>Looking for: ${escapeHtml(p.looking_for || "collaborators")}</p>
                `;
                container.appendChild(card);
            });
        }

        if (!data.mentors.length && !data.active_rooms.length && !data.projects.length) {
            container.innerHTML = "<div class='card'><p>Nothing nearby yet. Share location or check back later.</p></div>";
        }
    } catch (err) {
        container.innerHTML = `<div class="card">${escapeHtml(err.message)}</div>`;
    }
}

async function loadPeople() {
    const container = document.getElementById("peopleList");
    try {
        const data = await api("/api/people-you-may-know");
        container.innerHTML = "";
        if (!data.people.length) {
            container.innerHTML = "<div class='card'><p>No suggestions yet. Add skills and join groups to improve matches.</p></div>";
            return;
        }
        data.people.forEach(p => {
            const card = document.createElement("div");
            card.className = "mentor-card";
            card.innerHTML = `
                <div class="avatar">${escapeHtml(p.name.charAt(0).toUpperCase())}</div>
                <h3>${escapeHtml(p.name)} ${p.identity_verified ? "✓" : ""}</h3>
                <p>${escapeHtml(p.headline || "")}</p>
                <p>${escapeHtml(p.faculty || "")} · ${escapeHtml(p.course || "")}</p>
                <p class="skills">${escapeHtml(p.skills || "")}</p>
                <p class="distance">${escapeHtml(p.reasons.join(" · "))}</p>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        container.innerHTML = `<div class="card">${escapeHtml(err.message)}</div>`;
    }
}

/* -------------------------------------------------------
   GROUPS
------------------------------------------------------- */
let currentGroupId = null;

async function loadGroups() {
    const container = document.getElementById("groups");
    document.getElementById("groupDetail").classList.add("hidden");
    try {
        const groups = await api("/api/groups");
        container.innerHTML = "";
        groups.forEach(g => {
            const card = document.createElement("div");
            card.className = "group-card";
            card.innerHTML = `
                <span class="eyebrow">${escapeHtml(g.faculty || "COMMUNITY")}</span>
                <h3>${escapeHtml(g.name)}</h3>
                <strong>${escapeHtml(g.topic || "")}</strong>
                <p>${escapeHtml(g.description || "")}</p>
                <p>👥 ${g.members} members</p>
                <button class="primary-button" onclick="${g.joined ? `openGroup(${g.id}, '${escapeJs(g.name)}')` : `joinGroup(${g.id})`}">
                    ${g.joined ? "Open" : "Join"}
                </button>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        container.innerHTML = `<div class="card">${escapeHtml(err.message)}</div>`;
    }
}

async function createGroup() {
    try {
        await api("/api/groups", {
            method: "POST",
            body: JSON.stringify({
                name: document.getElementById("groupName").value,
                faculty: document.getElementById("groupFaculty").value,
                topic: document.getElementById("groupTopic").value,
                description: document.getElementById("groupDescription").value
            })
        });
        ["groupName", "groupFaculty", "groupTopic", "groupDescription"].forEach(id => {
            document.getElementById(id).value = "";
        });
        await loadGroups();
    } catch (err) {
        alert(err.message);
    }
}

async function joinGroup(id) {
    try {
        await api(`/api/groups/${id}/join`, { method: "POST" });
        await loadGroups();
    } catch (err) {
        alert(err.message);
    }
}

async function openGroup(id, name) {
    currentGroupId = id;
    document.getElementById("groupDetailName").textContent = name;
    document.getElementById("groupDetail").classList.remove("hidden");
    document.getElementById("groups").classList.add("hidden");
    await loadGroupPosts(id);
}

function closeGroupDetail() {
    document.getElementById("groupDetail").classList.add("hidden");
    document.getElementById("groups").classList.remove("hidden");
    currentGroupId = null;
}

async function loadGroupPosts(groupId) {
    const container = document.getElementById("groupPosts");
    try {
        const posts = await api(`/api/groups/${groupId}/posts`);
        container.innerHTML = "";
        posts.forEach(p => {
            const el = document.createElement("div");
            el.className = "feed-item";
            el.innerHTML = `
                <strong>${escapeHtml(p.name)}</strong>
                <p>${escapeHtml(p.body)}</p>
                <small>${new Date(p.created_at).toLocaleString()}</small>
            `;
            container.appendChild(el);
        });
    } catch (err) {
        container.innerHTML = `<p>${escapeHtml(err.message)}</p>`;
    }
}

async function createGroupPost() {
    if (!currentGroupId) return;
    const text = document.getElementById("groupPostText");
    if (!text.value.trim()) return;
    try {
        await api(`/api/groups/${currentGroupId}/posts`, {
            method: "POST",
            body: JSON.stringify({ body: text.value })
        });
        text.value = "";
        await loadGroupPosts(currentGroupId);
    } catch (err) {
        alert(err.message);
    }
}

async function createRoomFromGroup() {
    if (!currentGroupId) return;
    const name = prompt("Room name", "Study Session") || "Study Session";
    try {
        const res = await api(`/api/groups/${currentGroupId}/rooms`, {
            method: "POST",
            body: JSON.stringify({ name })
        });
        alert("Room created. Go to Rooms to join.");
        showPage("rooms");
    } catch (err) {
        alert(err.message);
    }
}

/* -------------------------------------------------------
   PROJECTS
------------------------------------------------------- */
async function loadProjects() {
    const container = document.getElementById("projects");
    try {
        const list = await api("/api/projects");
        container.innerHTML = "";
        list.forEach(p => {
            const card = document.createElement("div");
            card.className = "group-card";
            card.innerHTML = `
                <span class="eyebrow">${escapeHtml(p.faculty || "PROJECT")}</span>
                <h3>${escapeHtml(p.title)}</h3>
                <p>${escapeHtml(p.description || "")}</p>
                <p class="skills">Looking for: ${escapeHtml(p.looking_for || "collaborators")}</p>
                <p>👤 ${escapeHtml(p.owner_name)} · ${p.members} members</p>
                <button class="primary-button" onclick="joinProject(${p.id})">Join</button>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        container.innerHTML = `<div class="card">${escapeHtml(err.message)}</div>`;
    }
}

async function createProject() {
    try {
        await api("/api/projects", {
            method: "POST",
            body: JSON.stringify({
                title: document.getElementById("projectTitle").value,
                description: document.getElementById("projectDesc").value,
                looking_for: document.getElementById("projectLooking").value
            })
        });
        document.getElementById("projectTitle").value = "";
        document.getElementById("projectDesc").value = "";
        document.getElementById("projectLooking").value = "";
        await loadProjects();
    } catch (err) {
        alert(err.message);
    }
}

async function joinProject(id) {
    try {
        await api(`/api/projects/${id}/join`, { method: "POST" });
        alert("Joined project.");
        await loadProjects();
    } catch (err) {
        alert(err.message);
    }
}

/* -------------------------------------------------------
   SKILL EXCHANGE
------------------------------------------------------- */
async function loadSkillExchanges() {
    const container = document.getElementById("skillExchanges");
    try {
        const list = await api("/api/skill-exchanges");
        container.innerHTML = "";
        if (!list.length) {
            container.innerHTML = "<div class='card'><p>No open skill exchanges yet. Create the first one!</p></div>";
            return;
        }
        list.forEach(s => {
            const card = document.createElement("div");
            card.className = "group-card";
            card.innerHTML = `
                <h3>${escapeHtml(s.from_user.name)}</h3>
                <p><strong>Offers:</strong> ${escapeHtml(s.offer_skill)}</p>
                <p><strong>Wants:</strong> ${escapeHtml(s.request_skill)}</p>
                <p>${escapeHtml(s.message || "")}</p>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        container.innerHTML = `<div class="card">${escapeHtml(err.message)}</div>`;
    }
}

async function createSkillExchange() {
    try {
        await api("/api/skill-exchanges", {
            method: "POST",
            body: JSON.stringify({
                offer_skill: document.getElementById("offerSkill").value,
                request_skill: document.getElementById("requestSkill").value,
                message: document.getElementById("exchangeMsg").value
            })
        });
        document.getElementById("offerSkill").value = "";
        document.getElementById("requestSkill").value = "";
        document.getElementById("exchangeMsg").value = "";
        await loadSkillExchanges();
    } catch (err) {
        alert(err.message);
    }
}

/* -------------------------------------------------------
   ROOMS + WEBRTC (robust)
------------------------------------------------------- */
async function loadRooms() {
    const container = document.getElementById("rooms");
    try {
        const rooms = await api("/api/rooms");
        container.innerHTML = "";
        if (!rooms.length) {
            container.innerHTML = "<div class='card'><h3>No live rooms yet</h3><p>Join a group and start a study room from the group page.</p></div>";
            return;
        }
        rooms.forEach(r => {
            const card = document.createElement("div");
            card.className = "room-card";
            card.innerHTML = `
                <span class="eyebrow">LIVE STUDY ROOM</span>
                <h3>🎥 ${escapeHtml(r.name)}</h3>
                <p>${escapeHtml(r.group_name)}</p>
                <button class="primary-button" onclick="openVideoRoom(${r.id}, '${escapeJs(r.name)}')">Enter room</button>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        console.error(err);
    }
}

function connectSocket() {
    if (socket) return;
    socket = io();

    socket.on("existing_peers", async data => {
        for (const peerId of data.peers) {
            await createPeer(peerId, true);
        }
    });

    socket.on("participant_joined", data => {
        peerNames[data.sid] = data.name || "SFU Student";
    });

    socket.on("signal", async message => {
        const peerId = message.from;
        const signal = message.data;
        if (!peerConnections[peerId]) {
            await createPeer(peerId, false);
        }
        const peer = peerConnections[peerId];
        try {
            if (signal.type === "offer") {
                await peer.setRemoteDescription(new RTCSessionDescription(signal));
                // flush pending candidates
                const queued = pendingCandidates[peerId] || [];
                for (const c of queued) {
                    try { await peer.addIceCandidate(c); } catch {}
                }
                pendingCandidates[peerId] = [];
                const answer = await peer.createAnswer();
                await peer.setLocalDescription(answer);
                sendSignal(peerId, peer.localDescription);
            } else if (signal.type === "answer") {
                await peer.setRemoteDescription(new RTCSessionDescription(signal));
                const queued = pendingCandidates[peerId] || [];
                for (const c of queued) {
                    try { await peer.addIceCandidate(c); } catch {}
                }
                pendingCandidates[peerId] = [];
            } else if (signal.candidate) {
                if (peer.remoteDescription && peer.remoteDescription.type) {
                    await peer.addIceCandidate(new RTCIceCandidate(signal));
                } else {
                    pendingCandidates[peerId] = pendingCandidates[peerId] || [];
                    pendingCandidates[peerId].push(new RTCIceCandidate(signal));
                }
            }
        } catch (err) {
            console.error("Signal error", err);
        }
    });

    socket.on("participant_left", data => removePeer(data.sid));
    socket.on("room_error", data => alert(data.message));
    socket.on("new_notification", () => loadNotifications());
}

async function openVideoRoom(roomId, roomName) {
    activeRoomId = roomId;
    document.getElementById("activeRoomName").textContent = roomName;
    document.getElementById("videoRoom").classList.remove("hidden");

    try {
        // fetch ICE config (includes TURN if configured)
        const cfg = await api("/api/webrtc-config");
        iceServers = cfg.iceServers || iceServers;

        localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        addLocalVideo();
        socket.emit("join_video_room", { room_id: roomId });
        document.getElementById("videoRoom").scrollIntoView({ behavior: "smooth" });
    } catch (err) {
        alert("Camera/microphone permission is required (use HTTPS or localhost).");
    }
}

function addLocalVideo() {
    const grid = document.getElementById("videoGrid");
    if (document.getElementById("local-video")) return;
    const tile = document.createElement("div");
    tile.className = "video-tile";
    tile.id = "local-video";
    const video = document.createElement("video");
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    video.srcObject = localStream;
    const label = document.createElement("div");
    label.className = "video-label";
    label.textContent = `${currentUser.name} (You)`;
    tile.appendChild(video);
    tile.appendChild(label);
    grid.appendChild(tile);
}

async function createPeer(peerId, initiator) {
    if (peerConnections[peerId]) return peerConnections[peerId];

    const peer = new RTCPeerConnection({ iceServers });
    peerConnections[peerId] = peer;
    pendingCandidates[peerId] = [];

    if (localStream) {
        localStream.getTracks().forEach(track => peer.addTrack(track, localStream));
    }

    peer.onicecandidate = event => {
        if (event.candidate) sendSignal(peerId, event.candidate);
    };

    peer.ontrack = event => {
        addRemoteVideo(peerId, event.streams[0]);
    };

    peer.onconnectionstatechange = () => {
        if (["failed", "closed", "disconnected"].includes(peer.connectionState)) {
            removePeer(peerId);
        }
    };

    if (initiator) {
        const offer = await peer.createOffer();
        await peer.setLocalDescription(offer);
        sendSignal(peerId, peer.localDescription);
    }
    return peer;
}

function sendSignal(peerId, data) {
    socket.emit("signal", { to: peerId, data });
}

function addRemoteVideo(peerId, stream) {
    let tile = document.getElementById(`peer-${peerId}`);
    if (!tile) {
        tile = document.createElement("div");
        tile.className = "video-tile";
        tile.id = `peer-${peerId}`;
        const video = document.createElement("video");
        video.autoplay = true;
        video.playsInline = true;
        video.srcObject = stream;
        tile.appendChild(video);
        const label = document.createElement("div");
        label.className = "video-label";
        label.textContent = peerNames[peerId] || "SFU Student";
        tile.appendChild(label);
        document.getElementById("videoGrid").appendChild(tile);
    }
}

function removePeer(peerId) {
    const peer = peerConnections[peerId];
    if (peer) peer.close();
    delete peerConnections[peerId];
    delete pendingCandidates[peerId];
    delete peerNames[peerId];
    const tile = document.getElementById(`peer-${peerId}`);
    if (tile) tile.remove();
}

function toggleCamera() {
    if (!localStream) return;
    localStream.getVideoTracks().forEach(t => { t.enabled = !t.enabled; });
}

function toggleMicrophone() {
    if (!localStream) return;
    localStream.getAudioTracks().forEach(t => { t.enabled = !t.enabled; });
}

async function toggleScreen() {
    try {
        if (screenStream) {
            screenStream.getTracks().forEach(t => t.stop());
            screenStream = null;
            // restore camera
            if (localStream) {
                const videoTrack = localStream.getVideoTracks()[0];
                Object.values(peerConnections).forEach(pc => {
                    const sender = pc.getSenders().find(s => s.track && s.track.kind === "video");
                    if (sender && videoTrack) sender.replaceTrack(videoTrack);
                });
            }
            return;
        }
        screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true });
        const screenTrack = screenStream.getVideoTracks()[0];
        Object.values(peerConnections).forEach(pc => {
            const sender = pc.getSenders().find(s => s.track && s.track.kind === "video");
            if (sender) sender.replaceTrack(screenTrack);
        });
        screenTrack.onended = () => toggleScreen();
    } catch (err) {
        console.error(err);
    }
}

function leaveVideoRoom() {
    if (socket) socket.emit("leave_video_room");
    Object.keys(peerConnections).forEach(removePeer);
    if (localStream) {
        localStream.getTracks().forEach(t => t.stop());
        localStream = null;
    }
    if (screenStream) {
        screenStream.getTracks().forEach(t => t.stop());
        screenStream = null;
    }
    const localVideo = document.getElementById("local-video");
    if (localVideo) localVideo.remove();
    document.getElementById("videoRoom").classList.add("hidden");
    activeRoomId = null;
}

/* -------------------------------------------------------
   PROFILE + PORTFOLIO + CV
------------------------------------------------------- */
function populateProfile() {
    if (!currentUser) return;
    document.getElementById("profileName").textContent = currentUser.name;
    document.getElementById("profileHeadline").textContent = currentUser.headline || "";
    document.getElementById("profileFaculty").textContent =
        `${currentUser.faculty || ""} · ${currentUser.course || ""} ${currentUser.year_of_study || ""}`;

    document.getElementById("profileNameInput").value = currentUser.name || "";
    document.getElementById("profileHeadlineInput").value = currentUser.headline || "";
    document.getElementById("profileFacultyInput").value = currentUser.faculty || "";
    document.getElementById("profileCourseInput").value = currentUser.course || "";
    document.getElementById("profileYearInput").value = currentUser.year_of_study || "";
    document.getElementById("profileSkillsInput").value = currentUser.skills || "";
    document.getElementById("profileBioInput").value = currentUser.bio || "";
    document.getElementById("portfolioJsonInput").value = currentUser.portfolio_json || "[]";
    document.getElementById("mentorToggle").checked = currentUser.is_mentor;
    document.getElementById("discoverableToggle").checked = currentUser.discoverable;
    document.getElementById("showLocationToggle").checked = currentUser.show_location;
    document.getElementById("showPortfolioToggle").checked = currentUser.show_portfolio;
    document.getElementById("showSkillsToggle").checked = currentUser.show_skills;
}

async function saveProfile() {
    try {
        await api("/api/me", {
            method: "PATCH",
            body: JSON.stringify({
                name: document.getElementById("profileNameInput").value,
                headline: document.getElementById("profileHeadlineInput").value,
                faculty: document.getElementById("profileFacultyInput").value,
                course: document.getElementById("profileCourseInput").value,
                year_of_study: document.getElementById("profileYearInput").value,
                skills: document.getElementById("profileSkillsInput").value,
                bio: document.getElementById("profileBioInput").value,
                portfolio_json: document.getElementById("portfolioJsonInput").value,
                is_mentor: document.getElementById("mentorToggle").checked,
                discoverable: document.getElementById("discoverableToggle").checked,
                show_location: document.getElementById("showLocationToggle").checked,
                show_portfolio: document.getElementById("showPortfolioToggle").checked,
                show_skills: document.getElementById("showSkillsToggle").checked
            })
        });
        currentUser = await api("/api/me");
        populateProfile();
        alert("Profile & portfolio saved.");
    } catch (err) {
        alert(err.message);
    }
}

function downloadCV() {
    window.open("/api/cv", "_blank");
}

/* -------------------------------------------------------
   AI ASSISTANT
------------------------------------------------------- */
async function askAI() {
    const input = document.getElementById("aiPrompt");
    const prompt = input.value.trim();
    if (!prompt) return;
    const chat = document.getElementById("aiChat");
    const userMsg = document.createElement("div");
    userMsg.className = "ai-msg user";
    userMsg.textContent = prompt;
    chat.appendChild(userMsg);
    input.value = "";
    chat.scrollTop = chat.scrollHeight;

    try {
        const res = await api("/api/ai/assist", {
            method: "POST",
            body: JSON.stringify({ prompt })
        });
        const botMsg = document.createElement("div");
        botMsg.className = "ai-msg bot";
        botMsg.textContent = res.answer;
        chat.appendChild(botMsg);
        chat.scrollTop = chat.scrollHeight;
    } catch (err) {
        const botMsg = document.createElement("div");
        botMsg.className = "ai-msg bot";
        botMsg.textContent = err.message;
        chat.appendChild(botMsg);
    }
}

document.getElementById("aiPrompt")?.addEventListener("keydown", e => {
    if (e.key === "Enter") askAI();
});

/* -------------------------------------------------------
   NOTIFICATIONS
------------------------------------------------------- */
async function loadNotifications() {
    try {
        const notes = await api("/api/notifications");
        const badge = document.getElementById("notifBadge");
        const unread = notes.filter(n => !n.is_read).length;
        if (unread > 0) {
            badge.textContent = unread;
            badge.classList.remove("hidden");
        } else {
            badge.classList.add("hidden");
        }
        const list = document.getElementById("notifList");
        list.innerHTML = notes.length ? "" : "<p style='padding:8px;color:var(--muted)'>No notifications</p>";
        notes.forEach(n => {
            const el = document.createElement("div");
            el.className = "notif-item";
            el.innerHTML = `<strong>${escapeHtml(n.title)}</strong><br><span style="color:var(--muted);font-size:13px">${escapeHtml(n.body)}</span>`;
            list.appendChild(el);
        });
    } catch {}
}

function toggleNotifications() {
    document.getElementById("notifPanel").classList.toggle("hidden");
    loadNotifications();
}

async function markAllRead() {
    try {
        await api("/api/notifications/read", { method: "POST" });
        loadNotifications();
    } catch {}
}

/* -------------------------------------------------------
   REPORTING
------------------------------------------------------- */
async function reportUser(userId) {
    const reason = prompt("Why are you reporting this student?");
    if (!reason) return;
    try {
        await api("/api/reports", {
            method: "POST",
            body: JSON.stringify({
                target_type: "user",
                target_id: userId,
                reason,
                details: "Reported from discovery"
            })
        });
        alert("Report submitted.");
    } catch (err) {
        alert(err.message);
    }
}

async function reportRoom() {
    const reason = prompt("Why are you reporting this room?");
    if (!reason) return;
    try {
        await api("/api/reports", {
            method: "POST",
            body: JSON.stringify({
                target_type: "room",
                target_id: activeRoomId,
                reason,
                details: "Reported during live room"
            })
        });
        alert("Report submitted.");
    } catch (err) {
        alert(err.message);
    }
}

/* -------------------------------------------------------
   SECURITY HELPERS
------------------------------------------------------- */
function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function escapeJs(value) {
    return String(value)
        .replaceAll("\\", "\\\\")
        .replaceAll("'", "\\'")
        .replaceAll("\n", "\\n")
        .replaceAll("\r", "");
}

/* -------------------------------------------------------
   START
------------------------------------------------------- */
initialise();
