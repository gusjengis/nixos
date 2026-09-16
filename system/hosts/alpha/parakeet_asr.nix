{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.parakeetAsr;

  server = pkgs.writeText "parakeet-asr-server.py" ''
    import io
    import os
    import threading

    import librosa
    import numpy as np
    import soundfile as sf
    import torch
    from fastapi import FastAPI, File, HTTPException, UploadFile
    from transformers import AutoModelForTDT, AutoProcessor

    model_id = os.environ.get("PARAKEET_MODEL", "nvidia/parakeet-tdt-0.6b-v3")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForTDT.from_pretrained(model_id, dtype="auto")
    model.to(device)
    model.eval()

    target_sr = processor.feature_extractor.sampling_rate
    lock = threading.Lock()
    app = FastAPI(title="Parakeet ASR")


    def decode_audio(data: bytes):
      try:
        audio, sample_rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
      except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read audio: {exc}") from exc

      if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

      if sample_rate != target_sr:
        audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=target_sr)

      return audio


    @app.get("/health")
    def health():
      return {
        "ok": True,
        "model": model_id,
        "device": str(device),
        "cuda": torch.cuda.is_available(),
      }


    @app.post("/transcribe")
    @app.post("/v1/audio/transcriptions")
    async def transcribe(file: UploadFile = File(...)):
      audio = decode_audio(await file.read())
      inputs = processor(audio=[audio], sampling_rate=target_sr, return_tensors="pt")
      inputs = inputs.to(device)

      with lock, torch.inference_mode():
        output = model.generate(**inputs, return_dict_in_generate=True)

      decoded = processor.decode(output.sequences, skip_special_tokens=True)
      text = decoded[0] if isinstance(decoded, list) else decoded
      return {"text": text}
  '';

  startScript = pkgs.writeShellScript "parakeet-asr-start" ''
    exec ${lib.getExe pkgs.docker} run --name=parakeet-asr --rm --pull=missing --device=nvidia.com/gpu=all --network=host \
      -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
      -e NVIDIA_VISIBLE_DEVICES=all \
      -e HF_HOME=/data/huggingface \
      -e TRANSFORMERS_CACHE=/data/huggingface \
      -e TORCH_HOME=/data/torch \
      -e PIP_CACHE_DIR=/data/pip \
      -e PARAKEET_MODEL=${lib.escapeShellArg cfg.model} \
      -v ${toString cfg.dataDir}:/data \
      -v ${server}:/app/server.py:ro \
      ${lib.escapeShellArg cfg.image} \
      bash -lc ${lib.escapeShellArg ''
        apt-get update && \
        apt-get install -y --no-install-recommends git libsndfile1 && \
        rm -rf /var/lib/apt/lists/* && \
        python -m pip install --upgrade --cache-dir /data/pip \
          "git+https://github.com/huggingface/transformers" \
          accelerate fastapi "uvicorn[standard]" python-multipart soundfile librosa && \
        exec python -m uvicorn server:app --app-dir /app --host ${cfg.listenAddress} --port ${toString cfg.port}
      ''}
  '';
in
{
  options.parakeetAsr = {
    enable = lib.mkEnableOption "Parakeet V3 speech-to-text service";

    model = lib.mkOption {
      type = lib.types.str;
      default = "nvidia/parakeet-tdt-0.6b-v3";
      description = "Hugging Face model id to serve.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8765;
      description = "TCP port for the transcription HTTP API.";
    };

    listenAddress = lib.mkOption {
      type = lib.types.str;
      default = "0.0.0.0";
      description = "Address uvicorn listens on inside the host network namespace.";
    };

    dataDir = lib.mkOption {
      type = lib.types.path;
      default = /var/lib/parakeet-asr;
      description = "Persistent cache directory for models and Python packages.";
    };

    image = lib.mkOption {
      type = lib.types.str;
      default = "pytorch/pytorch:2.7.1-cuda12.6-cudnn9-runtime";
      description = "CUDA 12 container image used to run the ASR server.";
    };
  };

  config = lib.mkIf cfg.enable {
    virtualisation.docker.enable = true;
    hardware.nvidia-container-toolkit.enable = true;

    systemd.tmpfiles.rules = [
      "d ${toString cfg.dataDir} 0755 root root -"
      "d ${toString cfg.dataDir}/pip 0755 root root -"
      "d ${toString cfg.dataDir}/huggingface 0755 root root -"
    ];

    systemd.services.parakeet-asr = {
      description = "Parakeet V3 speech-to-text service";
      after = [
        "docker.service"
        "network-online.target"
      ]
      ++ lib.optionals config.tailscale.enable [ "tailscaled.service" ];
      wants = [
        "docker.service"
        "network-online.target"
      ]
      ++ lib.optionals config.tailscale.enable [ "tailscaled.service" ];
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "simple";
        Restart = "always";
        RestartSec = 10;
        ExecStartPre = "-${lib.getExe pkgs.docker} rm -f parakeet-asr";
        ExecStart = startScript;
        ExecStop = "${lib.getExe pkgs.docker} stop parakeet-asr";
        ExecStopPost = "-${lib.getExe pkgs.docker} rm -f parakeet-asr";
      };
    };

    networking.firewall.allowedTCPPorts = [ cfg.port ];
  };
}
