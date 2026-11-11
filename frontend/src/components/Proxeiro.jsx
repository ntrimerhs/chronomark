import '../styles/proxeiro.css'
import '../styles/uploadTheme.css'
import React,{useCallback, useEffect, useMemo, useRef, useState} from 'react';
import axios from 'axios';  ///do in terminal npm install axios
import { API_BASE_URL } from '../config';
import {
    CloudUpload,
    MessageCircle,
    ChevronRight,
    LoaderCircle,
    RefreshCw,
    Play,
    Pause,
    Volume2,
    VolumeX,
    Maximize2,
    X,
} from 'lucide-react';

const YtIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.5 12 3.5 12 3.5s-7.5 0-9.4.6A3 3 0 0 0 .5 6.2 31 31 0 0 0 0 12a31 31 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1c1.9.6 9.4.6 9.4.6s7.5 0 9.4-.6a3 3 0 0 0 2.1-2.1A31 31 0 0 0 24 12a31 31 0 0 0-.5-5.8zM9.75 15.5v-7l6.5 3.5-6.5 3.5z"/>
    </svg>
);
//pip install "fastapi[standard]"
//to run fastapi dev main.py
//npm i video.js
import VideoJSPlayer from './VideoJSPlayer';
import ChatBot from './Chatbot.jsx'

/* What the pipeline is made of, and a meter that idles until a file arrives. */
/* The four stops of the track, and where each backend stage lands on it. */
const TRACK_STEPS = ['INPUT', 'EXTRACT', 'INDEX', 'READY']

const STAGE_TO_STEP = {
    idle: 0,
    uploading: 0,
    queued: 0,
    downloading: 0,
    extracting_audio: 1,
    processing_audio_and_frames: 1,
    transcribing_audio: 1,
    embedding_text: 2,
    finalizing: 2,
    completed: 3,
    failed: 0,
}

const PIPELINE_SPEC = [
    ['ASR', 'whisper · large-v3'],
    ['INDEX', 'qdrant · local'],
    ['EMBED', 'minilm · 384d'],
    ['ANSWER', 'deepseek · cited'],
]

const METER_BARS = [18, 34, 26, 48, 62, 41, 55, 73, 46, 58, 36, 66, 82, 54, 44, 68, 90, 61, 47, 72, 52, 38, 64, 49, 30, 57, 42, 70]

const Proxeiro = () => {

    const [file, setFile] = useState(null);
    const [uploadProgress, setUploadProgres] = useState(0);
    const [backendProgress, setBackendProgress] = useState(0);
    const [uploadedFileURL, setUploadedFileURL] = useState(null);
    const [currentVideoId, setCurrentVideoId] = useState(null);
    const [uploadError, setUploadError] = useState('');
    const [isUploading, setIsUploading] = useState(false);
    const [processingStage, setProcessingStage] = useState('idle');
    const [showYoutubeInput, setShowYoutubeInput] = useState(false);
    const [youtubeUrl, setYoutubeUrl] = useState('');
    const [isPlaying, setIsPlaying] = useState(false);
    const [isMuted, setIsMuted] = useState(false);
    const [volume, setVolume] = useState(1);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);

    const playerRef = React.useRef(null);
    const uploadInputRef = useRef(null);
    const replaceInputRef = useRef(null);
    const seekTrackRef = useRef(null);
    const isScrubbingRef = useRef(false);

    useEffect(() => {
        return () => {
            setIsUploading(false);
        };
    }, []);

    const stageLabel = (stage) => {
        if (stage === 'extracting_audio') return '🎵 Extracting audio...';
        if (stage === 'transcribing_audio') return '📝 Transcribing (this may take a minute)...';
        if (stage === 'embedding_text') return '🧠 Creating embeddings...';
        if (stage === 'downloading') return '📥 Downloading from YouTube...';
        if (stage === 'processing_audio_and_frames') return '⚙️ Processing audio...';
        if (stage === 'queued') return '⏳ Queued for processing...';
        if (stage === 'finalizing') return '✨ Finalizing...';
        if (stage === 'completed') return '✅ Done!';
        if (stage === 'failed') return '❌ Processing failed.';
        return '';
    };

    const wait = (ms) => new Promise((resolve) => {
        setTimeout(resolve, ms);
    });

    const pollUploadStatus = async (jobId) => {
        const statusUrl = `${API_BASE_URL}/upload-status/${jobId}`;

        for (let attempt = 0; attempt < 600; attempt += 1) {
            const { data } = await axios.get(statusUrl);
            const status = data?.status;
            const stage = data?.stage || 'processing';
            const progress = Number(data?.progress ?? 0);
            setProcessingStage(stage);
            if (!Number.isNaN(progress)) {
                setBackendProgress(Math.max(0, Math.min(100, progress)));
            }

            if (status === 'completed') {
                const result = data?.result || {};
                const fileUrl = `${API_BASE_URL}${result.file_url}?t=${Date.now()}`;
                setUploadedFileURL(fileUrl);
                setCurrentVideoId(result.video_id ?? null);
                return;
            }

            if (status === 'failed') {
                throw new Error(data?.error || 'Upload processing failed.');
            }

            await wait(1200);
        }

        throw new Error('Processing timed out. Try a shorter video or retry.');
    };

    const uploadVideo = async (fileToUpload) => {
        const url = `${API_BASE_URL}/uploadfile/`;
        const formData = new FormData();
        formData.append('file_upload', fileToUpload);
        formData.append('filename', fileToUpload.name);

        try{
            setIsUploading(true);
            setUploadError('');
            setUploadedFileURL(null);
            setCurrentVideoId(null);
            setIsPlaying(false);
            setCurrentTime(0);
            setDuration(0);
            setProcessingStage('uploading');
            setBackendProgress(0);
            const config = {
                onUploadProgress: progressEvent => {
                    const total = progressEvent.total || 1;
                    const percentCompleted = Math.round((progressEvent.loaded * 100) / total);
                    setUploadProgres(percentCompleted);
                }
            }
            const response = await axios.post(url, formData, config);
            setUploadProgres(100);
            const jobId = response?.data?.job_id;

            if (jobId) {
                setProcessingStage('queued');
                await pollUploadStatus(jobId);
                setBackendProgress(100);
                setProcessingStage('completed');
            } else if (response?.data?.file_url) {
                // Backward-compatible path for synchronous backend responses.
                const fileUrl = `${API_BASE_URL}${response.data.file_url}?t=${Date.now()}`;
                setUploadedFileURL(fileUrl);
                setCurrentVideoId(response?.data?.video_id ?? null);
                setBackendProgress(100);
                setProcessingStage('completed');
            } else {
                throw new Error('Unexpected backend response. Missing job_id or file_url.');
            }
        }catch(error){
            setUploadError(error?.message || 'Upload failed. Check that the FastAPI backend is running and try again.');
            setProcessingStage('failed');
            if(error.response){
                console.log(error.response.data);
                console.log(error.response.status);
                console.log(error.response.headers);
            }else if(error.request){
                console.log(error.request);
            }else{
                console.log('Error', error.message);
            }
        } finally {
            setIsUploading(false);
        }
    };

    const handleChange = (event) =>{
        const nextFile = event.target.files[0] ?? null;
        if (!nextFile) {
            return;
        }

        setFile(nextFile);
        setUploadError('');
        setUploadProgres(0);
        setBackendProgress(0);

        if (uploadedFileURL) {
            uploadVideo(nextFile);
        }
    }

    const handleUploadAreaClick = () => {
        if (uploadInputRef.current) {
            uploadInputRef.current.value = '';
            uploadInputRef.current.click();
        }
    };

    const handleReplaceClick = () => {
        if (replaceInputRef.current) {
            replaceInputRef.current.value = '';
            replaceInputRef.current.click();
        }
    };

    const handleDragOver = (event) => {
        event.preventDefault();
    };

    const handleDrop = (event) => {
        event.preventDefault();
        const droppedFile = event.dataTransfer.files?.[0] ?? null;
        if (!droppedFile) {
            return;
        }
        setFile(droppedFile);
        setUploadError('');
        setUploadProgres(0);
        setBackendProgress(0);
    };

    //async function handleSubmit(event){
    const handleSubmit = async (event) => {

        event.preventDefault();

        if (!file) {
            setUploadError('Select a video file before uploading.');
            return;
        }

        await uploadVideo(file);
    }

    const submitYoutubeUrl = async (event) => {
        event.preventDefault();
        const url = youtubeUrl.trim();
        if (!url) return;

        try {
            setIsUploading(true);
            setUploadError('');
            setUploadedFileURL(null);
            setCurrentVideoId(null);
            setIsPlaying(false);
            setCurrentTime(0);
            setDuration(0);
            setProcessingStage('downloading');
            setBackendProgress(3);

            const response = await axios.post(`${API_BASE_URL}/download-youtube/`, { url });
            const jobId = response?.data?.job_id;
            if (!jobId) throw new Error('No job_id returned from server');

            setShowYoutubeInput(false);
            setYoutubeUrl('');
            await pollUploadStatus(jobId);
            setBackendProgress(100);
            setProcessingStage('completed');
        } catch (error) {
            setUploadError(error?.response?.data?.detail || error?.message || 'YouTube download failed.');
            setProcessingStage('failed');
        } finally {
            setIsUploading(false);
        }
    };

    //https://medium.com/@codeawake/ai-chatbot-frontend-1823b9c78521
    //https://github.com/ruizguille/tech-trends-chatbot

    //http://github.com/videojs/video.js/issues/5307
    //mp4 created with hevc is not supported by chrome only safary 

    const videoJsOptions = useMemo(() => ({
        //https://legacy.videojs.org/guides/options/
        autoplay: false,
        loop: true,
        controls: false,
        // Disable video.js's own click-to-toggle so it doesn't double-fire
        // alongside our custom onClick handlers (that was causing clicks to
        // appear to do nothing).
        userActions: { click: false },
        responsive: true,
        fill: true,   // fill parent container dimensions
        backgroundColor: "black",
        display: "block",
        forward:5,
        sources: [
        {
            src: uploadedFileURL,
            type: 'video/mp4',
        },
        ],
    }), [uploadedFileURL]);

    const displayProgress = processingStage === 'uploading' ? uploadProgress : backendProgress;

    // Keyboard control while watching. Space plays and pauses, the arrows move
    // ten seconds either way, F and Escape toggle fullscreen. Anything typed in
    // the chat box is left alone, otherwise a space in a question would pause
    // the video.
    React.useEffect(() => {
        const SKIP = 10;

        const isTyping = (target) => {
            if (!target) return false;
            const tag = target.tagName;
            return (
                tag === 'INPUT' ||
                tag === 'TEXTAREA' ||
                tag === 'SELECT' ||
                target.isContentEditable
            );
        };

        const handleKeyDown = (event) => {
            const player = playerRef.current;
            if (!player || player.isDisposed() || isTyping(event.target)) return;
            if (event.ctrlKey || event.metaKey || event.altKey) return;

            if (event.code === 'Space') {
                event.preventDefault();
                if (player.paused()) player.play();
                else player.pause();
                return;
            }

            if (event.key === 'ArrowRight') {
                event.preventDefault();
                const duration = player.duration();
                const target = player.currentTime() + SKIP;
                player.currentTime(
                    Number.isFinite(duration) && duration > 0 ? Math.min(target, duration) : target,
                );
                return;
            }

            if (event.key === 'ArrowLeft') {
                event.preventDefault();
                player.currentTime(Math.max(0, player.currentTime() - SKIP));
                return;
            }

            if (event.key === 'Escape' || event.key === 'f' || event.key === 'F') {
                event.preventDefault();
                if (player.isFullscreen()) player.exitFullscreen();
                else player.requestFullscreen();
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);

    const handlePlayerReady = (player) => {
        playerRef.current = player;

        player.on('waiting', () => {
        console.log('Player is waiting');
        });

        player.on('dispose', () => {
        console.log('Player will dispose');
        });

        player.on('play', () => setIsPlaying(true));
        player.on('pause', () => setIsPlaying(false));
        player.on('volumechange', () => {
            setIsMuted(player.muted() || player.volume() === 0);
            setVolume(player.volume());
        });
        player.on('loadedmetadata', () => setDuration(player.duration() || 0));
        player.on('durationchange', () => setDuration(player.duration() || 0));
        player.on('timeupdate', () => {
            if (!isScrubbingRef.current) {
                setCurrentTime(player.currentTime() || 0);
            }
            const liveDuration = player.duration();
            if (liveDuration) {
                setDuration((prev) => (prev === liveDuration ? prev : liveDuration));
            }
        });
    };

    const togglePlay = () => {
        const player = playerRef.current;
        if (!player) return;
        if (player.paused()) {
            player.play();
        } else {
            player.pause();
        }
    };

    const toggleMute = () => {
        const player = playerRef.current;
        if (!player) return;
        player.muted(!player.muted());
    };

    const handleVolumeChange = (event) => {
        const player = playerRef.current;
        if (!player) return;
        const nextVolume = Number(event.target.value);
        setVolume(nextVolume);
        player.volume(nextVolume);
        player.muted(nextVolume === 0);
    };

    const toggleFullscreen = () => {
        const player = playerRef.current;
        if (!player) return;
        if (player.isFullscreen()) {
            player.exitFullscreen();
        } else {
            player.requestFullscreen();
        }
    };

    const scrubToPointer = (event) => {
        const player = playerRef.current;
        const track = seekTrackRef.current;
        if (!player || !track) return;
        // Read duration directly from the player instead of React state,
        // which can lag behind (or never update) if loadedmetadata fires
        // before this component re-renders.
        const liveDuration = player.duration() || duration;
        if (!liveDuration) return;
        const rect = track.getBoundingClientRect();
        const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
        const time = ratio * liveDuration;
        setCurrentTime(time);
        player.currentTime(time);
    };

    const handleSeekPointerDown = (event) => {
        event.stopPropagation();
        event.currentTarget.setPointerCapture(event.pointerId);
        isScrubbingRef.current = true;
        scrubToPointer(event);
    };

    const handleSeekPointerMove = (event) => {
        if (!isScrubbingRef.current) return;
        scrubToPointer(event);
    };

    const handleSeekPointerUp = (event) => {
        event.stopPropagation();
        if (!isScrubbingRef.current) return;
        isScrubbingRef.current = false;
        scrubToPointer(event);
    };

    const formatTime = (seconds) => {
        if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
        const total = Math.floor(seconds);
        const m = Math.floor(total / 60);
        const s = String(total % 60).padStart(2, '0');
        return `${m}:${s}`;
    };

    // Stable identity on purpose: the chat below is memoised, and a new function
    // on every render would defeat it and re-render every answer at the video's
    // timeupdate rate.
    const seekTo = useCallback((seconds) => {
        const player = playerRef.current;
        if (!player || typeof seconds !== 'number' || Number.isNaN(seconds)) {
            return;
        }
        player.currentTime(seconds);
        player.play();
    }, []);

    return(
        <section className="upload-shell">
            {!uploadedFileURL && (
                <div className="upload-hero">
                                        <h1>
                        Add a recording.
                        <br />
                        <em>Ask it anything.</em>
                    </h1>
                    <p className="upload-subtitle">
                        A file from this machine or a YouTube link. The pipeline transcribes it,
                        indexes every passage, and hands you the second an answer came from.
                    </p>

                            <div className="upload-spec" aria-hidden="true">
                                {PIPELINE_SPEC.map(([key, value]) => (
                                    <div className="upload-spec-row" key={key}>
                                        <span>{key}</span>
                                        <i />
                                        <strong>{value}</strong>
                                    </div>
                                ))}

                                <div className="upload-meter">
                                    {METER_BARS.map((height, index) => (
                                        <span
                                            key={`bar-${index}`}
                                            style={{ '--h': `${height}%`, '--d': `${index * 62}ms` }}
                                        />
                                    ))}
                                </div>

                                <p className="upload-spec-note">Idle / waiting for a source</p>
                            </div>
                </div>
            )}

            <div className={`upload-grid${uploadedFileURL ? ' upload-grid-loaded' : ''}`}>
                <div className="upload-center-card">
                    {!uploadedFileURL ? (
                        <form className="upload-dropzone" onSubmit={handleSubmit}>
                            <input
                                ref={uploadInputRef}
                                className="upload-input"
                                type="file"
                                accept="video/*"
                                onChange={handleChange}
                            />

                            <button
                                type="button"
                                className="upload-dropzone-button"
                                onClick={handleUploadAreaClick}
                                onDragOver={handleDragOver}
                                onDrop={handleDrop}
                            >
                                <span className="upload-dropzone-icon">
                                    <CloudUpload size={48} strokeWidth={1.7} />
                                </span>
                                <span className="upload-dropzone-title">Drag and drop or click to upload</span>
                                <span className="upload-dropzone-copy">Supports video files and sends them directly to the backend processing pipeline.</span>
                            </button>

                            {showYoutubeInput ? (
                                <div className="yt-inline-form">
                                    <span className="yt-inline-icon"><YtIcon /></span>
                                    <input
                                        className="yt-inline-input"
                                        type="url"
                                        placeholder="Paste a YouTube URL…"
                                        value={youtubeUrl}
                                        onChange={(e) => setYoutubeUrl(e.target.value)}
                                        autoFocus
                                        onKeyDown={(e) => e.key === 'Enter' && submitYoutubeUrl(e)}
                                    />
                                    <button
                                        type="button"
                                        className="yt-inline-submit"
                                        onClick={submitYoutubeUrl}
                                        disabled={!youtubeUrl.trim() || isUploading}
                                    >
                                        {isUploading ? <LoaderCircle className="spin" size={15} /> : <ChevronRight size={15} />}
                                    </button>
                                    <button
                                        type="button"
                                        className="yt-inline-close"
                                        onClick={() => { setShowYoutubeInput(false); setYoutubeUrl(''); }}
                                    >
                                        <X size={15} />
                                    </button>
                                </div>
                            ) : (
                                <button
                                    type="button"
                                    className="yt-open-btn"
                                    onClick={() => setShowYoutubeInput(true)}
                                    disabled={isUploading}
                                >
                                    <YtIcon />
                                    Import from YouTube
                                </button>
                            )}

                            <div className="upload-form-footer">
                                <div className="upload-file-meta">
                                    <span className="upload-file-label">Selected file</span>
                                    <strong>{file ? file.name : 'No file selected yet'}</strong>
                                </div>
                                <button className="upload-submit" type="submit" disabled={!file || isUploading}>
                                    {isUploading ? <LoaderCircle className="spin" size={18} /> : <ChevronRight size={18} />}
                                    <span>{isUploading ? 'Working...' : 'Start analysis'}</span>
                                </button>
                            </div>

                            <div className="upload-progress-block">
                                <div className="upload-progress-labels">
                                    <span>Process / status</span>
                                    <span className="upload-progress-value">{displayProgress}%</span>
                                </div>

                                <div
                                    className="upload-track"
                                    role="progressbar"
                                    aria-valuemin={0}
                                    aria-valuemax={100}
                                    aria-valuenow={displayProgress}
                                    style={{ '--fill': Math.max(0, Math.min(100, displayProgress)) }}
                                >
                                    {TRACK_STEPS.map((step, index) => {
                                        const current = STAGE_TO_STEP[processingStage] ?? 0
                                        const done = index < current || (index === current && processingStage === 'completed')
                                        const idle = processingStage === 'idle'
                                        const active =
                                            index === current && !idle && processingStage !== 'completed'
                                        return (
                                            <div
                                                key={step}
                                                className={`upload-stop${done ? ' is-done' : ''}${active ? ' is-active' : ''}`}
                                            >
                                                <span className="upload-stop-dot" />
                                                <span className="upload-stop-label">{step}</span>
                                            </div>
                                        )
                                    })}
                                </div>

                                {stageLabel(processingStage) && (
                                    <p className="upload-file-label">{stageLabel(processingStage)}</p>
                                )}
                            </div>

                            {uploadError ? <p className="upload-error">{uploadError}</p> : null}
                        </form>
                    ) : (
                        <div className="upload-loaded-stage">
                            <div className="upload-loaded-header">
                                <button className="upload-secondary-action" type="button" onClick={handleReplaceClick}>
                                    <RefreshCw size={14} />
                                    Replace file
                                </button>
                                <button
                                    className="upload-secondary-action"
                                    type="button"
                                    onClick={() => {
                                        setShowYoutubeInput((prev) => !prev);
                                        setYoutubeUrl('');
                                    }}
                                    disabled={isUploading}
                                >
                                    <YtIcon />
                                    Import from YouTube
                                </button>
                                <input
                                    ref={replaceInputRef}
                                    className="upload-input"
                                    type="file"
                                    accept="video/*"
                                    onChange={handleChange}
                                />
                            </div>

                            {showYoutubeInput && (
                                <div className="yt-inline-form">
                                    <span className="yt-inline-icon"><YtIcon /></span>
                                    <input
                                        className="yt-inline-input"
                                        type="url"
                                        placeholder="Paste a YouTube URL…"
                                        value={youtubeUrl}
                                        onChange={(e) => setYoutubeUrl(e.target.value)}
                                        autoFocus
                                        onKeyDown={(e) => e.key === 'Enter' && submitYoutubeUrl(e)}
                                    />
                                    <button
                                        type="button"
                                        className="yt-inline-submit"
                                        onClick={submitYoutubeUrl}
                                        disabled={!youtubeUrl.trim() || isUploading}
                                    >
                                        {isUploading ? <LoaderCircle className="spin" size={15} /> : <ChevronRight size={15} />}
                                    </button>
                                    <button
                                        type="button"
                                        className="yt-inline-close"
                                        onClick={() => { setShowYoutubeInput(false); setYoutubeUrl(''); }}
                                    >
                                        <X size={15} />
                                    </button>
                                </div>
                            )}

                            {/* Only show a heading when there is a real file
                                name to show. The "Uploaded video" fallback
                                appeared above the player after an upload that
                                had no File object behind it, saying nothing the
                                player did not already say. */}
                            {file?.name && (
                                <h2 className="upload-video-title">{file.name}</h2>
                            )}

                            <div className={`video-stage${isPlaying ? ' video-stage-playing' : ''}`} onClick={togglePlay}>
                                <div className='video-container'>
                                    <VideoJSPlayer options={videoJsOptions} onReady={handlePlayerReady}/>
                                </div>

                                <div className="video-center-overlay">
                                    <button
                                        type="button"
                                        className="video-center-btn"
                                        onClick={(event) => { event.stopPropagation(); togglePlay(); }}
                                        aria-label={isPlaying ? 'Pause video' : 'Play video'}
                                    >
                                        {isPlaying ? <Pause size={26} /> : <Play size={26} />}
                                    </button>
                                </div>

                                <div className="video-controls-bar" onClick={(event) => event.stopPropagation()}>
                                    <div
                                        ref={seekTrackRef}
                                        className="video-seek-track"
                                        onPointerDown={handleSeekPointerDown}
                                        onPointerMove={handleSeekPointerMove}
                                        onPointerUp={handleSeekPointerUp}
                                    >
                                        <div
                                            className="video-seek-fill"
                                            style={{ width: `${duration ? (currentTime / duration) * 100 : 0}%` }}
                                        />
                                        <div
                                            className="video-seek-handle"
                                            style={{ left: `${duration ? (currentTime / duration) * 100 : 0}%` }}
                                        />
                                    </div>

                                    <div className="video-controls-row">
                                        <div className="video-controls-left">
                                            <button type="button" onClick={togglePlay} aria-label={isPlaying ? 'Pause' : 'Play'}>
                                                {isPlaying ? <Pause size={16} /> : <Play size={16} />}
                                            </button>
                                            <button type="button" onClick={toggleMute} aria-label={isMuted ? 'Unmute' : 'Mute'}>
                                                {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
                                            </button>
                                            <input
                                                type="range"
                                                className="video-volume-slider"
                                                min="0"
                                                max="1"
                                                step="0.01"
                                                value={isMuted ? 0 : volume}
                                                onChange={handleVolumeChange}
                                                aria-label="Volume"
                                            />
                                            <span className="video-time">{formatTime(currentTime)} / {formatTime(duration)}</span>
                                        </div>
                                        <button type="button" onClick={toggleFullscreen} aria-label="Fullscreen">
                                            <Maximize2 size={16} />
                                        </button>
                                    </div>
                                </div>
                            </div>

                        </div>
                    )}
                </div>

                {uploadedFileURL ? (
                    <div className="upload-chat-shell upload-chat-shell-inline">
                        <div className='chat-panel'>
                            <ChatBot onSeek={seekTo} videoId={currentVideoId} />
                        </div>
                    </div>
                ) : null}
            </div>

            {!uploadedFileURL ? (
                <div className="upload-lower-panel">
                    <div className="upload-chat-shell">
                        <div className="upload-chat-placeholder">
                            <MessageCircle size={20} strokeWidth={2} />
                            <input type="text" value="Upload a video to unlock the chat panel" readOnly />
                            <button type="button" disabled>
                                <ChevronRight size={18} strokeWidth={2} />
                            </button>
                        </div>
                    </div>
                </div>
            ) : null}
        </section>

    );

}

export default Proxeiro;