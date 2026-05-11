declare module "opus-recorder" {
  interface RecorderOptions {
    mediaTrackConstraints?: MediaStreamConstraints;
    encoderPath: string;
    bufferLength: number;
    encoderFrameSize: number;
    encoderSampleRate: number;
    maxFramesPerPage: number;
    numberOfChannels: number;
    recordingGain: number;
    resampleQuality: number;
    encoderComplexity: number;
    encoderApplication: number;
    streamPages: boolean;
  }

  export default class Recorder {
    constructor(options: RecorderOptions);
    start(): void;
    stop(): void;
    ondataavailable: (data: Uint8Array) => void;
    encodedSamplePosition: number;
  }
}
