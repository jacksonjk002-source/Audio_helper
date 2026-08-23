import { useCallback, useEffect, useRef, useState } from 'react'
import api from './api'
import './App.css'
const EXAMPLE_RESULT = `识别文字：
我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。

推荐碰面地点（Top 3）：
1. 星巴克（凤起路店）— 距中点约 320 米
   地址：杭州市下城区凤起路 567 号
   在高德地图中打开 ›

2. % Arabica（西湖店）— 距中点约 480 米
   地址：杭州市西湖区北山街 38 号
   在高德地图中打开 ›

3. Manner Coffee（龙翔桥店）— 距中点约 510 米
   地址：杭州市上城区平海路 58 号
   在高德地图中打开 ›

系统回复：
你们可以选下面三家咖啡店碰面：第一家星巴克离中点最近；第二家 Arabica 靠近西湖边；第三家 Manner 在龙翔桥地铁站附近，交通方便。`

const WEBM_MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
]

function pickWebmMimeType() {
  if (typeof MediaRecorder === 'undefined') return ''
  return WEBM_MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? ''
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const total = Math.round(seconds)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function App() {
  const [isRecording, setIsRecording] = useState(false)
  const [recordError, setRecordError] = useState('')
  const [recordingInfo, setRecordingInfo] = useState(null)
  // { blob, url, size, duration }
  const [uploadStatus, setUploadStatus] = useState('idle')
  // idle | uploading | success | error
  const [uploadedFilename, setUploadedFilename] = useState('')
  const [uploadError, setUploadError] = useState('')
  const mediaRecorderRef = useRef(null)
  const mediaStreamRef = useRef(null)
  const chunksRef = useRef([])
  const recordStartTimeRef = useRef(0)
  const recordingUrlRef = useRef(null)
  const isRecordingRef = useRef(false)

  const revokeRecordingUrl = useCallback(() => {
    if (recordingUrlRef.current) {
      URL.revokeObjectURL(recordingUrlRef.current)
      recordingUrlRef.current = null
    }
  }, [])

  const stopMediaStream = useCallback(() => {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop())
    mediaStreamRef.current = null
  }, [])

  const stopRecording = useCallback(() => {
    if (!isRecordingRef.current) return
    isRecordingRef.current = false
    setIsRecording(false)

    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
    } else {
      stopMediaStream()
    }
  }, [stopMediaStream])

  const startRecording = useCallback(async () => {
    if (isRecordingRef.current) return

    setRecordError('')
    revokeRecordingUrl()
    setRecordingInfo(null)
    setUploadStatus('idle')
    setUploadedFilename('')
    setUploadError('')
    chunksRef.current = []
    if (typeof MediaRecorder === 'undefined') {
      setRecordError('当前浏览器不支持 MediaRecorder')
      return
    }

    const mimeType = pickWebmMimeType()
    if (!mimeType) {
      setRecordError('当前浏览器不支持 webm 格式录音')
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream

      const recorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = recorder

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data)
        }
      }

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        chunksRef.current = []

        const elapsed = (Date.now() - recordStartTimeRef.current) / 1000
        const url = URL.createObjectURL(blob)
        recordingUrlRef.current = url

        setRecordingInfo({
          blob,
          url,
          size: blob.size,
          duration: elapsed,
        })

        stopMediaStream()
        mediaRecorderRef.current = null
      }

      recorder.onerror = () => {
        setRecordError('录音过程中发生错误，请重试')
        stopRecording()
      }

      recordStartTimeRef.current = Date.now()
      recorder.start()
      isRecordingRef.current = true
      setIsRecording(true)
    } catch (err) {
      stopMediaStream()
      if (err instanceof DOMException && err.name === 'NotAllowedError') {
        setRecordError('麦克风权限被拒绝，请在浏览器设置中允许访问')
      } else {
        setRecordError('无法启动录音，请检查麦克风设备')
      }
    }
  }, [revokeRecordingUrl, stopMediaStream, stopRecording])

  useEffect(() => {
    const blob = recordingInfo?.blob
    if (!blob) return

    let cancelled = false

    const uploadRecording = async () => {
      setUploadStatus('uploading')
      setUploadedFilename('')
      setUploadError('')

      const formData = new FormData()
      formData.append('file', blob, `recording_${Date.now()}.webm`)

      try {
        const { data } = await api.post('/upload', formData)
        if (cancelled) return

        if (data.success && data.filename) {
          setUploadStatus('success')
          setUploadedFilename(data.filename)
        } else {
          setUploadStatus('error')
          setUploadError('上传失败：服务器未返回有效文件名')
        }
      } catch {
        if (cancelled) return
        setUploadStatus('error')
        setUploadError('上传失败，请确认后端已在 8003 端口运行')
      }
    }

    uploadRecording()

    return () => {
      cancelled = true
    }
  }, [recordingInfo?.blob])

  const handlePlay = () => {    window.alert('语音播放功能下一步实现')
  }

  const handlePointerDown = (event) => {
    event.preventDefault()
    startRecording()
  }

  const handlePointerUp = (event) => {
    event.preventDefault()
    stopRecording()
  }

  useEffect(() => {
    return () => {
      isRecordingRef.current = false
      if (mediaRecorderRef.current?.state !== 'inactive') {
        mediaRecorderRef.current?.stop()
      }
      stopMediaStream()
      revokeRecordingUrl()
    }
  }, [revokeRecordingUrl, stopMediaStream])

  return (
    <div className="app">
      <header className="header">
        <h1 className="title">语音约碰面</h1>
        <p className="subtitle">说出两人位置和想做什么，帮你找中间的碰面地点</p>
      </header>

      <main className="main">
        <button
          type="button"
          className={`record-btn${isRecording ? ' record-btn--recording' : ''}`}
          onPointerDown={handlePointerDown}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
          onPointerCancel={handlePointerUp}
          aria-label={isRecording ? '正在录音，松开停止' : '按住说话'}
          aria-pressed={isRecording}
        >
          <span className="record-btn__icon" aria-hidden="true" />
          <span className="record-btn__label">
            {isRecording ? '录音中…' : '按住说话'}
          </span>
        </button>

        {(recordError || recordingInfo) && (
          <section className="recording-panel" aria-label="录音预览">
            <h2 className="recording-panel__heading">本次录音</h2>

            {recordError && (
              <p className="recording-panel__error" role="alert">
                {recordError}
              </p>
            )}

            {recordingInfo && (
              <div className="recording-panel__body">
                <dl className="recording-panel__meta">
                  <div className="recording-panel__meta-row">
                    <dt>时长</dt>
                    <dd>{formatDuration(recordingInfo.duration)}</dd>
                  </div>
                  <div className="recording-panel__meta-row">
                    <dt>大小</dt>
                    <dd>{formatSize(recordingInfo.size)}</dd>
                  </div>
                  <div className="recording-panel__meta-row">
                    <dt>格式</dt>
                    <dd>audio/webm</dd>
                  </div>
                </dl>
                <audio
                  className="recording-panel__player"
                  controls
                  src={recordingInfo.url}
                  onLoadedMetadata={(event) => {
                    const audioDuration = event.currentTarget.duration
                    if (Number.isFinite(audioDuration) && audioDuration > 0) {
                      setRecordingInfo((prev) =>
                        prev ? { ...prev, duration: audioDuration } : prev,
                      )
                    }
                  }}
                >
                  您的浏览器不支持音频播放
                </audio>
              </div>
            )}
          </section>
        )}

        <section className="result-panel" aria-label="识别与推荐结果">
          <h2 className="result-panel__heading">识别结果</h2>

          {uploadStatus === 'uploading' && (
            <p className="result-panel__upload-status">正在上传音频…</p>
          )}
          {uploadStatus === 'success' && uploadedFilename && (
            <p className="result-panel__upload-success">
              已上传至服务器：<strong>{uploadedFilename}</strong>
            </p>
          )}
          {uploadStatus === 'error' && uploadError && (
            <p className="result-panel__upload-error" role="alert">
              {uploadError}
            </p>
          )}

          <pre className="result-panel__content">{EXAMPLE_RESULT}</pre>
        </section>
        <button
          type="button"
          className="play-btn"
          onClick={handlePlay}
          aria-label="播放语音回复"
        >
          <span className="play-btn__icon" aria-hidden="true" />
          播放回复
        </button>
      </main>
    </div>
  )
}

export default App
