import { createFile } from 'mp4box'

/* Cutting a recording into pieces the edge can handle.

   The API accepts a video as ordered chunks (video_id, chunk_index,
   chunk_count, chunk_offset) and merges them with their offsets once the last
   one lands. This is the browser half: it re-muxes the file into self-contained
   MP4 pieces of at most `chunkSeconds`.

   Byte-splitting an MP4 does not work -- the moov/index boxes describe the whole
   file -- so each piece is built by copying the tracks and the samples that fall
   inside its window. Every step is guarded: if this cannot produce a valid piece
   the caller falls back to uploading the whole file, which is the path that has
   always worked. */

const MIN_CHUNK_BYTES = 1024

function toArrayBuffer(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(reader.error || new Error('could not read the file'))
    reader.readAsArrayBuffer(blob)
  })
}

function trackOptions(track) {
  const base = { timescale: track.timescale, type: track.codec, hdlr: track.type === 'video' ? 'vide' : 'soun' }
  if (track.video) {
    return { ...base, width: track.video.width, height: track.video.height }
  }
  if (track.audio) {
    return {
      ...base,
      samplerate: track.audio.sample_rate,
      channel_count: track.audio.channel_count,
      samplesize: track.audio.sample_size || 16,
    }
  }
  return null
}

export async function splitMp4(file, chunkSeconds = 600, onProgress) {
  try {
    const buffer = await toArrayBuffer(file)
    const input = createFile()

    const ready = new Promise((resolve, reject) => {
      input.onReady = (info) => resolve(info)
      input.onError = (error) => reject(new Error(`mp4box: ${error}`))
    })

    const tagged = buffer.slice(0)
    tagged.fileStart = 0
    input.appendBuffer(tagged)
    input.flush()

    const info = await ready
    const timescale = info.timescale || 1000
    const durationSeconds = info.duration / timescale
    if (!durationSeconds || durationSeconds < chunkSeconds * 1.2) {
      return null // not worth cutting
    }

    const writable = info.tracks.filter((track) => trackOptions(track))
    if (!writable.length) return null

    const windows = []
    for (let start = 0; start < durationSeconds; start += chunkSeconds) {
      windows.push({ start, length: Math.min(chunkSeconds, durationSeconds - start) })
    }

    const pieces = []
    for (let index = 0; index < windows.length; index += 1) {
      const { start, length } = windows[index]
      const begin = start * timescale
      const end = begin + length * timescale

      const output = createFile()
      const ids = {}
      for (const track of writable) {
        ids[track.id] = output.addTrack(trackOptions(track))
      }

      let samples = 0
      for (const track of writable) {
        const source = input.getTrackById(track.id)
        if (!source || !source.samples) continue
        for (const sample of source.samples) {
          const cts = sample.cts
          if (cts === undefined || cts < begin || cts >= end) continue
          const shifted = {
            ...sample,
            cts: cts - begin,
            dts: (sample.dts === undefined ? cts : sample.dts) - begin,
            is_sync: sample.is_sync,
          }
          output.addSample(ids[track.id], sample.data, shifted)
          samples += 1
        }
      }

      const data = output.getBuffer()
      if (!data || data.byteLength < MIN_CHUNK_BYTES || !samples) return null

      pieces.push({ blob: new Blob([data], { type: 'video/mp4' }), offset: start })
      if (onProgress) onProgress(index + 1, windows.length)
    }

    input.flush()
    return pieces.length > 1 ? pieces : null
  } catch (error) {
    console.warn('[split] falling back to the whole file:', error)
    return null
  }
}

export default splitMp4
