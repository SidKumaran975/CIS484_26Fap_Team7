/* Screen + webcam picture-in-picture, microphone and exam/system audio. */
class ExamCapture {
  constructor(){this.active=false;this.failed=false;this.parts=[];this.session=null;this.recorder=null;}
  async prepare(examiner){
    if(!navigator.mediaDevices?.getDisplayMedia)throw new Error('Screen recording requires HTTPS or localhost and a supported browser.');
    try {
      this.display=await navigator.mediaDevices.getDisplayMedia({video:{displaySurface:'monitor'},audio:true,systemAudio:'include'});
      if(!this.display.getAudioTracks().length)throw new Error('Share screen audio as well as video. Use Chrome or Edge and enable the audio checkbox in the screen-sharing dialog.');
      this.camera=await navigator.mediaDevices.getUserMedia({video:true,audio:true});
      this.context=new AudioContext();await this.context.resume();
      this.mix=this.context.createMediaStreamDestination();
      this.context.createMediaStreamSource(new MediaStream(this.camera.getAudioTracks())).connect(this.mix);
      if(this.display.getAudioTracks().length){
        this.context.createMediaStreamSource(new MediaStream(this.display.getAudioTracks())).connect(this.mix);
      }
      this.screenVideo=document.createElement('video');this.screenVideo.muted=true;this.screenVideo.srcObject=this.display;await this.screenVideo.play();
      this.camVideo=document.createElement('video');this.camVideo.muted=true;this.camVideo.srcObject=this.camera;await this.camVideo.play();
      this.canvas=document.createElement('canvas');this.canvas.width=1280;this.canvas.height=720;
      const paint=()=>{const ctx=this.canvas.getContext('2d');ctx.fillStyle='#000';ctx.fillRect(0,0,1280,720);ctx.drawImage(this.screenVideo,0,0,1280,720);ctx.drawImage(this.camVideo,960,480,320,240);};
      paint();this.paintTimer=setInterval(paint,1000/20);
      this.output=new MediaStream([...this.canvas.captureStream(20).getVideoTracks(),...this.mix.stream.getAudioTracks()]);
      const mime=['video/webm;codecs=vp8,opus','video/webm'].find(t=>MediaRecorder.isTypeSupported(t));
      if(!mime)throw new Error('This browser cannot record WebM video. Use Chrome or Edge.');
      this.recorder=new MediaRecorder(this.output,{mimeType:mime,videoBitsPerSecond:1500000});
      this.recorder.ondataavailable=e=>{if(e.data.size){const part={blob:e.data,index:this.parts.length,saved:false};this.parts.push(part);if(this.session)this.upload(part).catch(()=>{});}};
      this.recorder.onerror=()=>this.interrupt();
      for(const track of [...this.display.getTracks(),...this.camera.getTracks()])track.onended=()=>this.interrupt();
    }catch(error){await this.cancel();throw error;}
  }
  start(){this.started=new Date().toISOString();this.active=true;this.recorder.start(5000);}
  async bind(session){this.session=session;await this.event('recording_start',null,this.started);await Promise.all(this.parts.map(p=>this.upload(p)));if(this.failed){await this.finish(true);throw new Error('Recording access ended before the exam was ready.');}}
  event(event,interaction_id=null,timestamp=new Date().toISOString(),chunk_count=0){return api(`/api/sessions/${this.session}/recording-events`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event,interaction_id,timestamp,chunk_count})});}
  async upload(part){
    if(part.saved)return;
    if(part.uploading)return part.uploading;
    part.uploading=(async()=>{const form=new FormData();form.append('video',part.blob,'segment.webm');await api(`/api/sessions/${this.session}/recording-chunks/${part.index}`,{method:'POST',body:form});part.saved=true;part.blob=null;})();
    try{await part.uploading;}finally{part.uploading=null;}
  }
  async finish(interrupted=false){
    this.failed ||= interrupted;
    if(this.recorder?.state==='recording'){
      this.ended=new Date().toISOString();
      await new Promise(resolve=>{this.recorder.onstop=resolve;this.recorder.stop();});
    }
    if(!this.session){this.cleanup();return;}
    await Promise.all(this.parts.map(p=>this.upload(p)));
    await this.event(this.failed?'recording_interrupted':'recording_end',null,this.ended,this.parts.length);
    this.active=false;this.cleanup();
  }
  async interrupt(){if(!this.active||this.failed)return;this.failed=true;this.oninterrupted?.();try{await this.finish(true);}catch(error){document.getElementById('status').textContent=`Recording interrupted. Keep this page open to retry saving: ${error.message}`;const button=document.createElement('button');button.textContent='Retry saving interrupted recording';button.onclick=()=>this.finish(true).then(()=>button.remove()).catch(e=>{document.getElementById('status').textContent=e.message});document.getElementById('status').after(button);}}
  cleanup(){clearInterval(this.paintTimer);for(const stream of [this.display,this.camera,this.output])stream?.getTracks().forEach(t=>{t.onended=null;t.stop();});this.screenVideo?.pause();this.camVideo?.pause();if(this.context?.state!=='closed')this.context?.close();}
  async cancel(){this.active=false;if(this.recorder?.state==='recording'){this.recorder.ondataavailable=null;this.recorder.stop();}this.cleanup();this.parts=[];this.session=null;}
}
