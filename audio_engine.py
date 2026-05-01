import asyncio
import os
import subprocess
import tempfile
import shutil
import heapq
import edge_tts
from PySide6.QtCore import QThread, Signal
from dataclasses import dataclass, field
from text_processor import TextProcessor

@dataclass(order=True)
class ChunkResult:
    index: int
    filepath: str = field(compare=False)

class AudioEngine(QThread):
    progress = Signal(int, str)
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, source, output_path, config, is_raw_text=False):
        super().__init__()
        self.source = source
        self.output_path = output_path
        self.config = config
        self.is_raw_text = is_raw_text
        
        self.voice = config.get('voice')
        self.rate = config.get('rate')
        self.volume = config.get('volume')
        self.pitch = str(config.get('pitch', '+0Hz'))
        self.concurrency = config.get('concurrency', 10)
        self.chunk_size = config.get('chunk_size', 500)
        self.out_format = config.get('output_format', 'both')
        
        self.is_cancelled = False
        # Bounded queue prevents memory explosion if producer is faster than consumer
        self.queue = asyncio.Queue(maxsize=self.concurrency * 2) 
        self.heap = []
        self.total_tasks = 0 # Estimated total
        self.completed_tasks = 0
        self.temp_dir = tempfile.mkdtemp()
        
        # For accurate progress
        self.producer_finished = False

    async def producer(self):
        """
        Feeds text chunks into the queue. 
        """
        try:
            idx = 0
            # Stream chunks from processor
            for chunk in TextProcessor.chunk_generator(self.source, self.chunk_size, self.is_raw_text):
                if self.is_cancelled: break
                if not chunk: continue
                
                # Put blocks if queue is full, creating backpressure (good for memory)
                await self.queue.put((idx, chunk))
                
                # Update total count for progress bar (approximate)
                self.total_tasks = idx + 1 
                
                # Log progress of reading
                if idx % 20 == 0:
                    self.log.emit(f"Reading chunk {idx+1}...")
                    
                idx += 1
            
            # Signal end of production
            self.log.emit(f"Text processing complete. Total chunks: {idx}")
            
        except Exception as e:
            self.log.emit(f"Producer Error: {e}")
        finally:
            # Send sentinels (None) to stop consumers
            for _ in range(self.concurrency):
                await self.queue.put(None)

    async def consumer(self, worker_id):
        while True:
            if self.is_cancelled: break
            
            try:
                # Wait for item, but timeout periodically to check cancellation
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if item is None:
                self.queue.task_done()
                break
            
            idx, text = item
            temp_name = os.path.join(self.temp_dir, f"chunk_{idx}.mp3")
            
            try:
                # --- DETAILED LOGGING ---
                self.log.emit(f"Worker {worker_id}: Generating chunk {idx}...")
                
                communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, volume=self.volume, pitch=self.pitch)
                
                # --- TIMEOUT PROTECTION ---
                # If download takes > 60 seconds, abort this specific chunk
                await asyncio.wait_for(communicate.save(temp_name), timeout=60.0)
                
                # Push to heap for ordering
                heapq.heappush(self.heap, ChunkResult(index=idx, filepath=temp_name))
                
                self.completed_tasks += 1
                percent = int(10 + (self.completed_tasks / max(1, self.total_tasks)) * 80)
                self.progress.emit(percent, f"Generated {self.completed_tasks}/{self.total_tasks}")
                
            except asyncio.TimeoutError:
                self.log.emit(f"<font color='orange'>Warning: Chunk {idx} timed out (skipped).</font>")
            except Exception as e:
                self.log.emit(f"<font color='red'>Error chunk {idx}: {str(e)[:50]}</font>")
            finally:
                self.queue.task_done()

    async def run_async(self):
        self.progress.emit(0, "Starting pipeline...")
        
        # Run Producer and Consumers CONCURRENTLY
        # This fixes the "stuck at reading" issue
        consumers = [asyncio.create_task(self.consumer(i)) for i in range(self.concurrency)]
        producer_task = asyncio.create_task(self.producer())
        
        # Wait for producer to finish reading
        await producer_task
        
        # Wait for consumers to finish processing
        await asyncio.gather(*consumers)

        if self.is_cancelled:
            raise Exception("Cancelled.")

        self.progress.emit(90, "Assembling final audio...")
        
        mp3_file = f"{self.output_path}.mp3"
        wav_file = f"{self.output_path}.wav"
        
        list_file = os.path.join(self.temp_dir, "concat_list.txt")
        with open(list_file, 'w', encoding='utf-8') as f:
            while self.heap:
                item = heapq.heappop(self.heap)
                safe_path = item.filepath.replace('\\', '/').replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")
        
        # FFmpeg Execution
        if self.out_format in ['mp3', 'both']:
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", mp3_file]
            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode != 0:
                self.log.emit(f"FFmpeg MP3 Error: {proc.stderr.decode()[:100]}")

        if self.out_format in ['wav', 'both']:
            src = mp3_file if os.path.exists(mp3_file) else list_file
            input_flags = [] if os.path.exists(mp3_file) else ["-f", "concat", "-safe", "0"]
            cmd = ["ffmpeg", "-y"] + input_flags + ["-i", src, "-acodec", "pcm_s16le", "-ar", "44100", wav_file]
            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode != 0:
                 self.log.emit(f"FFmpeg WAV Error: {proc.stderr.decode()[:100]}")

        return mp3_file, wav_file

    def run(self):
        try:
            self.progress.emit(5, "Initializing async loop...")
            # Create new loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            mp3, wav = loop.run_until_complete(self.run_async())
            
            msg = "Success!\n"
            if os.path.exists(mp3): msg += f"MP3: {mp3}\n"
            if os.path.exists(wav): msg += f"WAV: {wav}"
            self.finished.emit(True, msg)
            
        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            try: shutil.rmtree(self.temp_dir)
            except: pass
            if loop and not loop.is_closed():
                loop.close()

    def cancel(self):
        self.is_cancelled = True