const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Track { constructor(kind){this.kind=kind;this.stopped=false;} clone(){return new Track(this.kind);} stop(){this.stopped=true;} }
class Stream { constructor(tracks=[]){this.tracks=tracks;} getTracks(){return this.tracks;} getAudioTracks(){return this.tracks.filter(t=>t.kind==='audio');} getVideoTracks(){return this.tracks.filter(t=>t.kind==='video');} }
class Recorder {
  static isTypeSupported(){return true;}
  constructor(stream){this.stream=stream;this.state='inactive';}
  start(){this.state='recording';}
  stop(){this.state='inactive';queueMicrotask(()=>{this.ondataavailable?.({data:new Blob(['final'])});this.onstop?.();});}
}
class Audio {
  async resume(){}
  async close(){}
  createMediaStreamDestination(){return {stream:new Stream([new Track('audio')])};}
  createMediaStreamSource(){return {connect(){}};}
  createMediaElementSource(){return {connect(){},disconnect(){}};}
}

async function run(){
  let failUpload=false, denyCamera=false;
  const calls=[], tracks=[];
  const screen=()=>{const stream=new Stream([new Track('video'),new Track('audio')]);tracks.push(...stream.getTracks());return stream;};
  const camera=()=>{if(denyCamera)throw new Error('permission denied');const stream=new Stream([new Track('video'),new Track('audio')]);tracks.push(...stream.getTracks());return stream;};
  const ctx={Blob,FormData,MediaStream:Stream,MediaRecorder:Recorder,AudioContext:Audio,Date,Promise,Error,
    setInterval:()=>1,clearInterval(){},
    navigator:{mediaDevices:{getDisplayMedia:async()=>screen(),getUserMedia:async()=>camera()}},
    document:{createElement:kind=>kind==='canvas'?{getContext:()=>({fillRect(){},drawImage(){}}),captureStream:()=>new Stream([new Track('video')])}:{play:async()=>{},pause(){}}},
    api:async(url,options)=>{calls.push({url,body:options.body});if(url.includes('recording-chunks')&&failUpload){failUpload=false;throw new Error('network unavailable');}return {ok:true};}
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('speech-to-text/session-recording.js','utf8')+'\nthis.ExamCapture=ExamCapture;',ctx);
  const capture=new ctx.ExamCapture();
  await capture.prepare({});capture.start();
  assert.equal(capture.output.getVideoTracks().length,1);
  assert.equal(capture.output.getAudioTracks().length,1);
  // Recording starts before session creation completes; retain early footage.
  capture.recorder.ondataavailable({data:new Blob(['early'])});
  assert.equal(capture.parts.length,1);
  await capture.bind('session');
  assert.equal(JSON.parse(calls[0].body).event,'recording_start');
  assert.equal(capture.parts[0].saved,true);
  failUpload=true;
  await assert.rejects(()=>capture.finish(),/network unavailable/);
  assert.equal(capture.active,true,'keep unsaved data available for retry');
  await capture.finish();
  assert.equal(capture.active,false);
  assert.equal(capture.parts.length,2);
  const end=JSON.parse(calls.at(-1).body);
  assert.equal(end.event,'recording_end');assert.equal(end.chunk_count,2);
  assert(tracks.every(t=>t.stopped));
  const interrupted=new ctx.ExamCapture();
  await interrupted.prepare({});interrupted.start();await interrupted.bind('interrupted');
  await interrupted.finish(true);
  assert.equal(JSON.parse(calls.at(-1).body).event,'recording_interrupted');
  denyCamera=true;
  const denied=new ctx.ExamCapture();
  await assert.rejects(()=>denied.prepare({}),/permission denied/);
  assert(tracks.every(t=>t.stopped),'stop screen capture when webcam permission is denied');
  console.log('PASS: capture lifecycle, early segments, upload retry, interruption, permission cleanup');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
