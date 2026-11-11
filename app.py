import os
from datetime import datetime
from uuid import uuid4
from urllib.parse import quote
from html import escape

import httpx
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

load_dotenv(override=True)

app = FastAPI(title="MeetFocus AI")
# PostgreSQL Database Connection

def get_db_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")

    return psycopg.connect(
        database_url,
        row_factory=dict_row
    )

# Create Database Tables
def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Meetings Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meetings (
            meeting_id TEXT PRIMARY KEY,
            created_at TEXT
        )
    """)

    # Participants Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS participants (
           id BIGSERIAL PRIMARY KEY,
            meeting_id TEXT,
            participant_name TEXT,
            face_visibility_score INTEGER DEFAULT 0,
            screen_facing_score INTEGER DEFAULT 0,
            joined_at TEXT,
            FOREIGN KEY (meeting_id) REFERENCES meetings(meeting_id)
        )
    """)

    conn.commit()
    conn.close()


create_tables()

def meeting_exists(meeting_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT meeting_id FROM meetings WHERE meeting_id = %s",
        (meeting_id,)
    )

    meeting = cursor.fetchone()
    conn.close()

    return meeting is not None 

# Temporary in-memory meeting storage. Meetings are cleared when the server restarts.

LIVEKIT_SANDBOX_ID = "meetfocusai-1cuxq8"
LIVEKIT_CONNECTION_DETAILS_URL = "https://cloud-api.livekit.io/api/sandbox/connection-details"


HOME_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MeetFocus AI</title>
    <style>
        * { box-sizing: border-box; }
        body {
            margin: 0; min-height: 100vh; font-family: Arial, sans-serif;
            color: #eef5ff; background: #0b1020;
            display: flex; align-items: center; justify-content: center;
            padding: 24px;
        }
              .card {
            width: 100%; max-width: 620px; padding: 38px;
            background: #151d35; border: 1px solid #263653;
            border-radius: 20px; box-shadow: 0 18px 50px #0006;
        }

        h1 {
            color: #67e8f9;
            margin: 0 0 10px;
            font-size: 34px;
        }
        .subtitle { color: #b8c5dc; margin-bottom: 30px; line-height: 1.5; }
        h2 { font-size: 19px; margin: 24px 0 12px; }
        input {
            width: 100%; padding: 13px 14px; border-radius: 9px;
            border: 1px solid #40516f; background: #0b1020;
            color: white; font-size: 15px; margin: 7px 0 12px;
        }
        button {
            width: 100%; padding: 13px; border: 0; border-radius: 9px;
            color: white; background: #0891b2; font-size: 16px;
            font-weight: bold; cursor: pointer;
        }
        button:hover { background: #0e7490; }
        .divider { border: 0; border-top: 1px solid #34435e; margin: 25px 0; }
        .note { color: #91a2bd; font-size: 13px; line-height: 1.5; }
    </style>
</head>
<body>
    <main class="card">
        <h1>MeetFocus AI</h1>
        <div class="subtitle">Meet Smarter with AI<br>
        An AI-based online meeting attention and alertness monitoring system.</div>

        <h2>Create a New Meeting</h2>
        <form action="/create" method="post">
            <button type="submit">Create Meeting</button>
        </form>

        <hr class="divider">

        <h2>Join an Existing Meeting</h2>
        <form action="/join" method="get">
            <input type="text" name="meeting_id" placeholder="Enter Meeting ID" required>
            <button type="submit">Join Meeting</button>
        </form>
        <p class="note">Create a meeting and share its meeting link with other participants.</p>
    </main>
</body>
</html>
"""


MEETING_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MeetFocus AI - Meeting</title>
    <style>
        * { box-sizing: border-box; }
        body {
            margin: 0; min-height: 100vh; padding: 24px;
            font-family: Arial, sans-serif; color: #eef5ff;
            background: #0b1020;
        }
        .container { max-width: 1100px; margin: auto; }
        .card {
            background: #151d35; border: 1px solid #263653;
            border-radius: 16px; padding: 24px; margin-bottom: 18px;
            box-shadow: 0 12px 35px #0004;
        }
        h1 { color: #67e8f9; margin: 0 0 8px; }
        h2 { margin: 0 0 15px; font-size: 20px; }
        .muted { color: #aebbd1; }
        .meeting-id { color: #67e8f9; font-weight: bold; }
        input {
            width: 100%; max-width: 420px; padding: 12px;
            border-radius: 8px; border: 1px solid #40516f;
            background: #0b1020; color: white; font-size: 15px;
            margin: 8px 0 12px;
        }
        button, .back-link {
            display: inline-block; padding: 11px 17px; border: 0;
            border-radius: 8px; color: white; background: #0891b2;
            font-size: 14px; font-weight: bold; cursor: pointer;
            text-decoration: none; margin: 4px 5px 4px 0;
        }
        button:hover, .back-link:hover { background: #0e7490; }
        .secondary { background: #334155; }
        .secondary:hover { background: #475569; }
        #status, #faceStatus {
            margin-top: 12px; padding: 11px; border-radius: 8px;
            background: #0b1020; color: #b8c5dc; line-height: 1.5;
        }
        #videoGrid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 14px; margin-top: 15px;
        }
        .video-box {
            min-height: 190px; padding: 10px; border-radius: 12px;
            background: #0b1020; border: 1px solid #34435e;
        }
        .video-box video { width: 100%; max-height: 360px; object-fit: cover; }
        .video-label { color: #aebbd1; font-size: 13px; margin-bottom: 8px; }
        .share-link {
            overflow-wrap: anywhere; padding: 12px; border-radius: 8px;
            background: #0b1020; color: #67e8f9; margin: 10px 0;
        }
        @media (max-width: 600px) {
            body { padding: 12px; }
            .card { padding: 17px; }
        }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/livekit-client/dist/livekit-client.umd.min.js"></script>
</head>
<body>
<div class="container">
    <section class="card">
        <h1>MeetFocus AI</h1>
        <p class="muted">Online Meeting Room</p>
        <p>Meeting ID: <span class="meeting-id" id="meetingId">__MEETING_ID__</span></p>
        <label for="participantName">Your Name</label><br>
        <input id="participantName" type="text" placeholder="Enter your name" value="Participant">
        <br>
        <button id="joinButton" onclick="startMeeting()">Join Video Meeting</button>
        <button class="secondary" onclick="leaveMeeting()">Leave Meeting</button>
        <div id="status">Ready to join the meeting.</div>
        <div id="faceStatus">Face detection: Waiting for camera.</div>
      <div class="card">
    <h2>AI Monitoring Dashboard</h2>

    <p id="attentionStatus">Status: Waiting...</p>
    <p id="headDirection">Head Direction: Waiting...</p>
    <p id="attentionIndicator">
    Attention Indicator: Waiting...
</p>

<p id="screenFacingScore">
    Screen Facing Score: 0%
</p>

    <h3>Face Visibility Score</h3>

    <h1 id="attentionScore">0%</h1>

    <div style="background:#334155; height:14px; border-radius:10px;">
        <div id="scoreBar"
             style="width:0%; height:14px; background:#06b6d4; border-radius:10px;">
        </div>
    </div>

    <p id="alertMessage">Monitoring not started.</p>
</div>
    </section>

    <section class="card" id="organizerDashboard" style="display:none;">

    <h2>Organizer Dashboard</h2>

    <p class="muted">
        Participants Monitoring Overview
    </p>
    <div class="monitor">
    <h3>Total Participants: <span id="totalParticipants">0</span></h3>
    <h3>Average Face Visibility: <span id="averageFace">0%</span></h3>
    <h3>Average Screen Facing: <span id="averageScreen">0%</span></h3>
</div>

    <div id="participantOverview">
        <p>Waiting for participants to join...</p>
    </div>

</section>

    <section class="card">
        <h2>Meeting Video</h2>
        <div id="videoGrid">
            <div class="video-box" id="localBox">
                <div class="video-label">Your Camera</div>
            </div>
            <div class="video-box" id="remoteBox">
                <div class="video-label">Other Participants</div>
            </div>
        </div>
    </section>

    <section class="card">
        <h2>Share Meeting Link</h2>
        <p class="muted">Share this link with people who need to join this meeting.</p>
        <div class="share-link" id="shareLink">__MEETING_LINK__</div>
        <button onclick="copyMeetingLink()">Copy Meeting Link</button>
        <a class="back-link secondary" href="/">Back to Home</a>
    </section>
</div>

<script type="module">
const meetingId = "__MEETING_ID__";
const statusBox = document.getElementById("status");
const faceStatus = document.getElementById("faceStatus");
const localBox = document.getElementById("localBox");
const remoteBox = document.getElementById("remoteBox");

let room = null;
let faceLandmarker = null;
let faceDetectionTimer = null;
let detectionStarted = false;
let faceSamples = [];
let screenFacingSamples = [];
let noFaceStartTime = null;

async function initializeFaceDetection() {
    try {
        faceStatus.textContent = "Face detection: Loading model...";
        const visionAPI = await import(
            "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs"
        );

        const vision = await visionAPI.FilesetResolver.forVisionTasks(
            "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm"
        );

        faceLandmarker = await visionAPI.FaceLandmarker.createFromOptions(
            vision,
            {
                baseOptions: {
                    modelAssetPath:
                        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
                },
                runningMode: "VIDEO",
                numFaces: 1
            }
        );

        faceStatus.textContent = "Face detection: Model ready. Join the meeting.";
        console.log("Face Landmarker initialized successfully.");
    } catch (error) {
        console.error("MediaPipe initialization error:", error);
        faceStatus.textContent = "Face detection unavailable: " + error.message;
    }
}
function getHeadDirection(landmarks) {
    const nose = landmarks[1];
    const leftEye = landmarks[33];
    const rightEye = landmarks[263];

    const eyeCenterX = (leftEye.x + rightEye.x) / 2;

    const difference = nose.x - eyeCenterX;

    if (difference < -0.035) {
        return "Face Right";
    } else if (difference > 0.035) {
        return "Face Left";
    } else {
        return "Face Center";
    }
}
function startFaceDetection
(videoElement) {
    if (detectionStarted) return;
    detectionStarted = true;

    faceDetectionTimer = setInterval(() => {

        if (!faceLandmarker || !videoElement ||
            videoElement.readyState < 2) return;

        try {
            const result = faceLandmarker.detectForVideo(
                videoElement,
                performance.now()
            );

            const faceFound =
                result.faceLandmarks &&
                result.faceLandmarks.length > 0;

                const facingScreen = faceFound &&
    getHeadDirection(result.faceLandmarks[0]) === "Face Center";

screenFacingSamples.push(facingScreen);

if (screenFacingSamples.length > 20) {
    screenFacingSamples.shift();
}

const facingCount = screenFacingSamples.filter(Boolean).length;

const screenScore = Math.round(
    (facingCount / screenFacingSamples.length) * 100
);



document.getElementById("screenFacingScore").textContent =
    "Screen Facing Score: " + screenScore + "%";
                
if (faceFound) {
    const landmarks = result.faceLandmarks[0];
    const direction = getHeadDirection(landmarks);

    document.getElementById("headDirection").textContent =
        "Head Direction: " + direction;

    const indicator =
        direction === "Face Center"
            ? "Face Visible - Facing Screen"
            : "Face Visible - Looking Sideways";

    document.getElementById("attentionIndicator").textContent =
        "Attention Indicator: " + indicator;

} else {
    document.getElementById("headDirection").textContent =
        "Head Direction: No Face";

    document.getElementById("attentionIndicator").textContent =
        "Attention Indicator: Face Not Visible";
}


            // Store recent face visibility samples
            faceSamples.push(faceFound);

            if (faceSamples.length > 20) {
                faceSamples.shift();
            }

            // Calculate face visibility score
            const visibleSamples =
                faceSamples.filter(Boolean).length;

            const score = Math.round(
                (visibleSamples / faceSamples.length) * 100
            );

            document.getElementById("attentionScore")
                .textContent = score + "%";

            document.getElementById("scoreBar")
                .style.width = score + "%";

            if (faceFound) {
                faceStatus.textContent =
                    "Face Detection: Face Detected";

                document.getElementById("attentionStatus")
                    .textContent = "Status: Face Visible";

                noFaceStartTime = null;

                document.getElementById("alertMessage")
                    .textContent = "Face is visible.";

            } else {
                faceStatus.textContent =
                    "Face Detection: No Face Detected";

                document.getElementById("attentionStatus")
                    .textContent = "Status: Face Not Visible";

                if (noFaceStartTime === null) {
                    noFaceStartTime = Date.now();
                }

                if (Date.now() - noFaceStartTime >= 5000) {
                    document.getElementById("alertMessage")
                        .textContent =
                        "Alert: Face has not been detected for 5 seconds!";
                }
            }

        } catch (error) {
            console.error("Face detection error:", error);
        }

    }, 500);
}


function addRemoteTrack(track, participant) {
    const element = track.attach();

    element.style.width = "100%";
    element.style.borderRadius = "10px";

    const participantBox = document.createElement("div");
    participantBox.className = "video-box";

    const label = document.createElement("div");
    label.className = "video-label";
    label.textContent = participant.identity || "Participant";

    participantBox.appendChild(label);
    participantBox.appendChild(element);

    // Individual participant monitoring
    const monitor = document.createElement("div");

    monitor.style.padding = "10px";
    monitor.style.marginTop = "8px";
    monitor.style.background = "#151d35";
    monitor.style.borderRadius = "8px";

    const faceScore = document.createElement("p");
    faceScore.textContent = "Face Visibility: Waiting...";

    const screenScore = document.createElement("p");
    screenScore.textContent = "Screen Facing: Waiting...";

    const direction = document.createElement("p");
    direction.textContent = "Head Direction: Waiting...";

    const status = document.createElement("p");
    status.textContent = "Monitoring: Waiting...";

    monitor.appendChild(faceScore);
    monitor.appendChild(screenScore);
    monitor.appendChild(direction);
    monitor.appendChild(status);

    participantBox.appendChild(monitor);

    // Save elements for individual monitoring
    participantBox.monitorElements = {
        faceScore,
        screenScore,
        direction,
        status
    };

    participantBox.dataset.participantSid =
        participant.sid || participant.identity || "";

    // Save Meeting ID and Participant Name
participantBox.dataset.meetingId =
    window.location.pathname.split("/").pop();

participantBox.dataset.participantName =
    participant.identity || "Participant";    

    remoteBox.appendChild(participantBox);
    startParticipantMonitoring(element, participantBox);

    // Add participant to Organizer Dashboard
const overview = document.getElementById("participantOverview");
if (overview.textContent.includes("Waiting for participants to join...")) {
    overview.innerHTML = "";
}

const overviewCard = document.createElement("div");
overviewCard.style.padding = "12px";
overviewCard.style.marginTop = "10px";
overviewCard.style.background = "#1e293b";
overviewCard.style.borderRadius = "10px";

const overviewName = document.createElement("h3");
overviewName.textContent = participant.identity || "Participant";

const overviewFace = document.createElement("p");
overviewFace.textContent = "Face Visibility: Waiting...";

const overviewScreen = document.createElement("p");
overviewScreen.textContent = "Screen Facing: Waiting...";

const overviewStatus = document.createElement("p");
overviewStatus.textContent = "Monitoring: Waiting...";

overviewCard.appendChild(overviewName);
overviewCard.appendChild(overviewFace);
overviewCard.appendChild(overviewScreen);
overviewCard.appendChild(overviewStatus);

overview.appendChild(overviewCard);
participantBox.dashboardCard = overviewCard;

participantBox.dashboardElements = {
    overviewFace,
    overviewScreen,
    overviewStatus
};
}


function startParticipantMonitoring(videoElement, participantBox) {

    const samples = [];
    const facingSamples = [];

    const timer = setInterval(() => {

        if (!faceLandmarker || !videoElement ||
            videoElement.readyState < 2) {
            return;
        }

        try {
            const result = faceLandmarker.detectForVideo(
                videoElement,   
                performance.now()
            );

            const faceFound =
                result.faceLandmarks &&
                result.faceLandmarks.length > 0;

            samples.push(faceFound);

            if (samples.length > 20) {
                samples.shift();
            }

            const faceCount = samples.filter(Boolean).length;

            const faceScore = Math.round(
                (faceCount / samples.length) * 100
            );

            let directionText = "No Face";
            let facingScreen = false;

            if (faceFound) {
                const landmarks = result.faceLandmarks[0];

                directionText = getHeadDirection(landmarks);
                facingScreen = directionText === "Face Center";
            }

            facingSamples.push(facingScreen);

            if (facingSamples.length > 20) {
                facingSamples.shift();
            }

            const facingCount =
                facingSamples.filter(Boolean).length;

            const screenScore = Math.round(
                (facingCount / facingSamples.length) * 100
            );

            // Save scores to Database every 5 seconds
const now = Date.now();

if (!participantBox.lastScoreSave ||
    now - participantBox.lastScoreSave >= 5000) {

    participantBox.lastScoreSave = now;

    const params = new URLSearchParams({
        meeting_id: participantBox.dataset.meetingId,
        participant_name: participantBox.dataset.participantName,
        face_visibility_score: faceScore,
        screen_facing_score: screenScore
    });

    fetch("/save-score?" + params.toString(), {
        method: "POST"
    })
    .then(response => {
        if (!response.ok) {
            console.error("Score save failed:", response.status);
        }
    })
    .catch(error => {
        console.error("Database error:", error);
    });
}

            const ui = participantBox.monitorElements;

            ui.faceScore.textContent =
                "Face Visibility: " + faceScore + "%";

            ui.screenScore.textContent =
                "Screen Facing: " + screenScore + "%";

            ui.direction.textContent =
                "Head Direction: " + directionText;

            ui.status.textContent = faceFound
                ? "Monitoring: Face Visible"
                : "Monitoring: Face Not Visible";

                // Update Organizer Dashboard scores
const dashboard = participantBox.dashboardElements;
participantBox.dashboardValues = {
    faceScore: faceScore,
    screenScore: screenScore
};
dashboard.overviewFace.textContent =
    "Face Visibility: " + faceScore + "%";

dashboard.overviewScreen.textContent =
    "Screen Facing: " + screenScore + "%";

dashboard.overviewStatus.textContent = faceFound
    ? "Monitoring: Face Visible"
    : "Monitoring: Face Not Visible";

    // Calculate Organizer Dashboard Summary
const participantBoxes = document.querySelectorAll("#remoteBox .video-box");

let totalFace = 0;
let totalScreen = 0;
let count = 0;

participantBoxes.forEach(box => {
    if (box.dashboardValues) {
        totalFace += box.dashboardValues.faceScore;
        totalScreen += box.dashboardValues.screenScore;
        count++;
    }
});

document.getElementById("totalParticipants").textContent = count;

document.getElementById("averageFace").textContent =
    count > 0 ? Math.round(totalFace / count) + "%" : "0%";

document.getElementById("averageScreen").textContent =
    count > 0 ? Math.round(totalScreen / count) + "%" : "0%";

        } catch (error) {
            console.error("Participant monitoring error:", error);
        }

    }, 500);

    participantBox.monitorTimer = timer;
}



async function startMeeting() {

const meetingRole = new URLSearchParams(window.location.search).get("role") || "participant";

console.log("Current User Role:", meetingRole);

document.getElementById("organizerDashboard").style.display =
    meetingRole === "organizer" ? "block" : "none";
    const nameInput = document.getElementById("participantName");
    const participantName = nameInput.value.trim();

    if (!participantName) {
        statusBox.textContent = "Please enter your name.";
        return;
    }

    if (!window.LivekitClient) {
        statusBox.textContent = "LiveKit library could not load. Refresh the page and try again.";
        return;
    }

    document.getElementById("joinButton").disabled = true;
    statusBox.textContent = "Connecting to meeting...";

    try {
        const response = await fetch(
            "/get-token?meeting_id=" + encodeURIComponent(meetingId) +
            "&participant_name=" + encodeURIComponent(participantName)
        );

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || "Could not get meeting connection details.");
        }

        room = new LivekitClient.Room();

        room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, publication, participant) => {
            if (track.kind === "video") {
                addRemoteTrack(track, participant);
            } else if (track.kind === "audio") {
                const audioElement = track.attach();
                document.body.appendChild(audioElement);
            }
        });

       room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {
    const elements = track.detach();

    elements.forEach(element => {
        const participantBox = element.closest(".video-box");

        if (participantBox) {
            // Stop participant monitoring
            if (participantBox.monitorTimer) {
                clearInterval(participantBox.monitorTimer);
            }

            // Remove Organizer Dashboard card
            if (participantBox.dashboardCard) {
                participantBox.dashboardCard.remove();
            }

            // Remove participant video card
            participantBox.remove();

            // Update Organizer Dashboard Summary
const participantBoxes = document.querySelectorAll(
    "#remoteBox .video-box"
);

let totalFace = 0;
let totalScreen = 0;
let count = 0;

participantBoxes.forEach(box => {
    if (box.dashboardValues) {
        totalFace += box.dashboardValues.faceScore;
        totalScreen += box.dashboardValues.screenScore;
        count++;
    }
});

document.getElementById("totalParticipants").textContent = count;

document.getElementById("averageFace").textContent =
    count > 0 ? Math.round(totalFace / count) + "%" : "0%";

document.getElementById("averageScreen").textContent =
    count > 0 ? Math.round(totalScreen / count) + "%" : "0%";

        } else {
            element.remove();
        }
    });
});
// Handle participant completely leaving the meeting
room.on(
    LivekitClient.RoomEvent.ParticipantDisconnected,
    (participant) => {

        const participantBoxes = document.querySelectorAll(
            "#remoteBox .video-box"
        );

        participantBoxes.forEach(box => {

            if (
                box.dataset.participantSid === participant.sid ||
                box.dataset.participantSid === participant.identity
            ) {
                if (box.monitorTimer) {
                    clearInterval(box.monitorTimer);
                }

                if (box.dashboardCard) {
                    box.dashboardCard.remove();
                }

                box.remove();
            }
        });

        // Recalculate dashboard summary
        const remainingBoxes = document.querySelectorAll(
            "#remoteBox .video-box"
        );

        let totalFace = 0;
        let totalScreen = 0;
        let count = 0;

        remainingBoxes.forEach(box => {
            if (box.dashboardValues) {
                totalFace += box.dashboardValues.faceScore;
                totalScreen += box.dashboardValues.screenScore;
                count++;
            }
        });

        document.getElementById("totalParticipants").textContent = count;

        document.getElementById("averageFace").textContent =
            count > 0 ? Math.round(totalFace / count) + "%" : "0%";

        document.getElementById("averageScreen").textContent =
            count > 0 ? Math.round(totalScreen / count) + "%" : "0%";
    }
);

// Connect to LiveKit Room
await room.connect(data.server_url, data.token);

// Start Camera and Microphone
const localTracks = await LivekitClient.createLocalTracks({
    audio: true,
    video: true
});

// Publish tracks to meeting
for (const track of localTracks) {
    await room.localParticipant.publishTrack(track);
}

// Display Local Camera
const localVideoTrack = localTracks.find(
    track => track.kind === "video"
);

if (localVideoTrack) {
    const videoElement = localVideoTrack.attach();

    videoElement.style.width = "100%";
    videoElement.style.borderRadius = "10px";
    videoElement.autoplay = true;
    videoElement.playsInline = true;

    const localBox = document.getElementById("localBox");
    localBox.innerHTML = "";
    localBox.appendChild(videoElement);

    startFaceDetection(videoElement);
}

        statusBox.textContent = "Connected! Camera and microphone are active.";
    } catch (error) {
        console.error("Meeting connection error:", error);
        statusBox.textContent = "Could not connect: " + error.message;
        document.getElementById("joinButton").disabled = false;
    }
}


async function leaveMeeting() {

    // Stop Face Detection
    if (faceDetectionTimer) {
        clearInterval(faceDetectionTimer);
        faceDetectionTimer = null;
    }

    detectionStarted = false;

    if (room) {
        try {
            // Stop Camera and Microphone tracks
            const publications =
                room.localParticipant.trackPublications;

            publications.forEach(publication => {
                if (publication.track) {
                    publication.track.stop();
                    publication.track.detach();
                }
            });

            // Disconnect from LiveKit
            await room.disconnect();

        } catch (error) {
            console.error("Disconnect error:", error);
        }

        room = null;
    }

    // Stop Remote Participant Monitoring
    remoteBox.querySelectorAll(".video-box").forEach(box => {

        if (box.monitorTimer) {
            clearInterval(box.monitorTimer);
        }

        if (box.dashboardCard) {
            box.dashboardCard.remove();
        }

        box.remove();
    });

    // Remove Local Camera Video
    localBox.querySelectorAll("video").forEach(element => {
        element.remove();
    });

    // Reset Organizer Dashboard
    document.getElementById("totalParticipants").textContent = "0";
    document.getElementById("averageFace").textContent = "0%";
    document.getElementById("averageScreen").textContent = "0%";

    document.getElementById("participantOverview").innerHTML =
        "<p>Waiting for participants to join...</p>";

    // Update Status
    statusBox.textContent = "You have left the meeting.";
    faceStatus.textContent = "Face detection: Stopped.";

    document.getElementById("joinButton").disabled = false;
}


async function copyMeetingLink() {
    const link = document.getElementById("shareLink").textContent.trim();
    try {
        await navigator.clipboard.writeText(link);
        statusBox.textContent = "Meeting link copied!";
    } catch (error) {
        statusBox.textContent = "Copy failed. Please select and copy the meeting link manually.";
    }
}

window.startMeeting = startMeeting;
window.leaveMeeting = leaveMeeting;
window.copyMeetingLink = copyMeetingLink;

initializeFaceDetection();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def home():
    return HOME_PAGE


@app.post("/create")
async def create_meeting():
    meeting_id = uuid4().hex[:8]
    
    # Save meeting in PostgreSQL Database
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
    "INSERT INTO meetings (meeting_id, created_at) VALUES (%s, %s)",
    (meeting_id, datetime.now().isoformat())
)

    conn.commit()
    conn.close()

    return RedirectResponse(
        url=f"/meeting/{meeting_id}?role=organizer",
        status_code=303
    )




@app.get("/join")
async def join_meeting(meeting_id: str):
    meeting_id = meeting_id.strip()

    if not meeting_id:
        raise HTTPException(
            status_code=400,
            detail="Meeting ID is required."
        )

    if not meeting_exists(meeting_id):
        raise HTTPException(
            status_code=404,
            detail="Meeting ID not found. Ask the host to create a new meeting link."
        )

    return RedirectResponse(
        url=f"/meeting/{quote(meeting_id)}?role=participant",
        status_code=303
    )




@app.get("/meeting/{meeting_id}", response_class=HTMLResponse)
async def meeting_page(meeting_id: str, request: Request):
    if not meeting_exists(meeting_id):
        raise HTTPException(
            status_code=404,
            detail="Meeting not found. Please create a new meeting from the home page."
        )

    base_url = str(request.base_url).rstrip("/")
    meeting_link = f"{base_url}/join?meeting_id={quote(meeting_id)}"

    page = MEETING_PAGE.replace("__MEETING_ID__", escape(meeting_id))
    page = page.replace("__MEETING_LINK__", escape(meeting_link))

    return HTMLResponse(page)



@app.get("/get-token")
async def get_token(meeting_id: str, participant_name: str = "Participant"):
    meeting_id = meeting_id.strip()
    participant_name = participant_name.strip() or "Participant"

    if not meeting_exists(meeting_id):
        raise HTTPException(
            status_code=404,
            detail="Meeting ID not found."
        )

    headers = {"X-Sandbox-ID": LIVEKIT_SANDBOX_ID}

    payload = {
        "room_name": meeting_id,
        "participant_name": participant_name
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                LIVEKIT_CONNECTION_DETAILS_URL,
                headers=headers,
                json=payload
            )

        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"LiveKit sandbox error ({response.status_code}): {response.text[:300]}"
            )

        result = response.json()

        server_url = result.get("serverUrl") or result.get("server_url")
        token = result.get("participantToken") or result.get("participant_token")
        returned_name = result.get("participantName") or participant_name

        if not server_url or not token:
            raise HTTPException(
                status_code=502,
                detail="LiveKit response did not contain serverUrl and participantToken."
            )

        # Save Participant in PostgreSQL Database
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO participants
            (meeting_id, participant_name, joined_at)
            VALUES (%s, %s, %s)
            """,
            (meeting_id, returned_name, datetime.now().isoformat())
        )

        conn.commit()
        conn.close()

        return {
            "server_url": server_url,
            "participant_name": returned_name,
            "token": token
        }

    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail=f"Could not contact LiveKit sandbox: {str(error)}"
        )


    
@app.post("/save-score")
async def save_score(
    meeting_id: str,
    participant_name: str,
    face_visibility_score: int,
    screen_facing_score: int
):
    if not (0 <= face_visibility_score <= 100):
        raise HTTPException(status_code=400, detail="Invalid face score.")

    if not (0 <= screen_facing_score <= 100):
        raise HTTPException(status_code=400, detail="Invalid screen score.")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE participants
                SET face_visibility_score = %s,
            screen_facing_score = %s
                    WHERE id = (
            SELECT id FROM participants
            WHERE meeting_id = %s AND participant_name = %s
            ORDER BY id DESC
            LIMIT 1
        )
        """,
        (
            face_visibility_score,
            screen_facing_score,
            meeting_id,
            participant_name
        )
    )

    updated = cursor.rowcount
    conn.commit()
    conn.close()

    if updated == 0:
        raise HTTPException(
            status_code=404,
            detail="Participant record not found."
        )

    return {"message": "Scores saved successfully."}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
