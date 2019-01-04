# nlp-stocks
Forecast stock movements utilizing NLP on financial reports.

## Setup
Follow the instructions for installing tensorflow/tensorflow-gpu. After that install the following modules:
```
  source ./setup.sh
```

### Troubleshooting Tensorflow
- Ubuntu 18.04 is officially not supported (by Cuda 9.0 which tensorflow requires)
- The CPU needs to support AVX instructions (or use tensorflow==1.5.0)
- Follow these instructions: https://github.com/williamFalcon/tensorflow-gpu-install-ubuntu-16.04 (and the official tensorflow installation guide)
