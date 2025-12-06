#!/bin/bash
#
# DoRobot Environment Setup Script (Base Environment)
#
# This script installs all dependencies into the current conda base environment.
# Use this when you don't want to create a separate conda environment.
#
# Usage:
#   conda activate base  # or your existing environment
#   bash scripts/setup_env_base.sh [options]
#
# Options:
#   --device DEVICE   Device type: cpu, cuda11.8, cuda12.1, cuda12.4, npu (default: cpu)
#   --torch-npu VER   torch-npu version for NPU (default: 2.5.1)
#   --help            Show this help message

set -e

# Default configuration
DEVICE_TYPE="cpu"
TORCH_NPU_VERSION="2.5.1"
INSTALL_EXTRAS=""  # Optional: training, simulation, tensorflow, all
SKIP_CONFIRM=false  # If true, skip confirmation prompt

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --device)
                DEVICE_TYPE="$2"
                shift 2
                ;;
            --cuda)
                # Legacy support: --cuda 12.4 -> --device cuda12.4
                DEVICE_TYPE="cuda$2"
                shift 2
                ;;
            --npu)
                DEVICE_TYPE="npu"
                shift
                ;;
            --torch-npu)
                TORCH_NPU_VERSION="$2"
                shift 2
                ;;
            --extras)
                INSTALL_EXTRAS="$2"
                shift 2
                ;;
            --training)
                # Shorthand for --extras training
                if [ -z "$INSTALL_EXTRAS" ]; then
                    INSTALL_EXTRAS="training"
                else
                    INSTALL_EXTRAS="$INSTALL_EXTRAS,training"
                fi
                shift
                ;;
            --all)
                INSTALL_EXTRAS="all"
                shift
                ;;
            -y|--yes)
                SKIP_CONFIRM=true
                shift
                ;;
            --help|-h)
                print_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                print_usage
                exit 1
                ;;
        esac
    done
}

print_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "DoRobot Environment Setup (Base Environment)"
    echo ""
    echo "This script installs into the CURRENT conda environment (no new env created)."
    echo "Make sure you have activated your desired environment before running."
    echo ""
    echo "Options:"
    echo "  --device DEVICE   Device type: cpu, cuda11.8, cuda12.1, cuda12.4, npu (default: cpu)"
    echo "  --cuda VER        (Legacy) CUDA version: 11.8, 12.1, 12.4"
    echo "  --npu             Use Ascend NPU (equivalent to --device npu)"
    echo "  --torch-npu VER   torch-npu version for NPU (default: 2.5.1)"
    echo "  --extras EXTRAS   Optional dependencies: training, simulation, tensorflow, all"
    echo "  --training        Shorthand for --extras training"
    echo "  --all             Install all optional dependencies"
    echo "  -y, --yes         Skip confirmation prompt (for automation)"
    echo "  --help            Show this help message"
    echo ""
    echo "Dependency Groups:"
    echo "  (none)            Core only - data collection, robot control (fastest install)"
    echo "  training          + diffusers, wandb, matplotlib, numba (for policy training)"
    echo "  simulation        + gymnasium, pymunk, gym-pusht (for simulation envs)"
    echo "  tensorflow        + tensorflow, tensorflow-datasets (for TF dataset formats)"
    echo "  all               All of the above"
    echo ""
    echo "Examples:"
    echo "  conda activate base && $0              # Install to base, core only"
    echo "  conda activate base && $0 --npu       # Install to base with NPU support"
    echo "  conda activate myenv && $0 --training # Install to myenv with training deps"
    echo "  conda activate myenv && $0 -y         # Non-interactive install (CI/scripts)"
    echo ""
    echo "NPU Notes:"
    echo "  - Requires CANN toolkit to be installed on the system"
    echo "  - Tested on Ascend 310B with torch-npu 2.5.1"
    echo "  - Visit: https://www.hiascend.com for CANN installation"
}

# Get PyTorch install command based on device type
get_pytorch_install_cmd() {
    case $DEVICE_TYPE in
        "cpu")
            echo "pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu"
            ;;
        "cuda11.8")
            echo "pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118"
            ;;
        "cuda12.1")
            echo "pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121"
            ;;
        "cuda12.4")
            echo "pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124"
            ;;
        "npu")
            # For NPU, install PyTorch 2.5.1 (compatible with torch-npu 2.5.1)
            echo "pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu"
            ;;
        *)
            log_error "Unsupported device type: $DEVICE_TYPE"
            log_error "Supported types: cpu, cuda11.8, cuda12.1, cuda12.4, npu"
            exit 1
            ;;
    esac
}

# Install NPU-specific packages
install_npu_packages() {
    log_step "Installing Ascend NPU packages..."

    # Check if CANN is installed
    if [ -z "$ASCEND_HOME" ] && [ ! -d "/usr/local/Ascend" ]; then
        log_warn "ASCEND_HOME not set and /usr/local/Ascend not found."
        log_warn "Make sure CANN toolkit is installed for NPU support."
        log_warn "Visit: https://www.hiascend.com/software/cann"
    else
        ASCEND_PATH="${ASCEND_HOME:-/usr/local/Ascend}"
        log_info "Found Ascend installation at: $ASCEND_PATH"
    fi

    # Install torch-npu
    log_info "Installing torch-npu==$TORCH_NPU_VERSION..."
    pip install torch-npu==$TORCH_NPU_VERSION
}

# Find project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Main setup function
main() {
    parse_args "$@"

    echo ""
    echo "=========================================="
    echo "  DoRobot Environment Setup (Base)"
    echo "=========================================="
    echo ""

    # Check if we're in a conda environment
    if [ -z "$CONDA_DEFAULT_ENV" ]; then
        log_error "No conda environment is active."
        log_error "Please activate a conda environment first:"
        log_error "  conda activate base"
        log_error "Or use setup_env.sh to create a new environment."
        exit 1
    fi

    log_info "Current environment: $CONDA_DEFAULT_ENV"
    log_info "Device type: $DEVICE_TYPE"
    if [ "$DEVICE_TYPE" == "npu" ]; then
        log_info "torch-npu version: $TORCH_NPU_VERSION"
    fi
    if [ -n "$INSTALL_EXTRAS" ]; then
        log_info "Optional extras: $INSTALL_EXTRAS"
    else
        log_info "Optional extras: (none - core only, fastest install)"
    fi
    echo ""

    # Confirm installation
    if [ "$SKIP_CONFIRM" = true ]; then
        log_info "Installing packages into '$CONDA_DEFAULT_ENV' environment (non-interactive mode)..."
    else
        log_warn "This will install packages into '$CONDA_DEFAULT_ENV' environment."
        read -p "Continue? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Aborted."
            exit 0
        fi
    fi

    # Step 1: Install PyTorch
    log_step "Installing PyTorch ($DEVICE_TYPE)..."
    PYTORCH_CMD=$(get_pytorch_install_cmd)
    log_info "Running: $PYTORCH_CMD"
    eval "$PYTORCH_CMD"

    # Step 1.5: Install NPU packages if needed
    if [ "$DEVICE_TYPE" == "npu" ]; then
        install_npu_packages
    fi

    # Step 2: Install DORA-RS
    log_step "Installing DORA-RS..."
    pip install dora-rs-cli

    # Step 3: Install main project
    log_step "Installing DoRobot project dependencies..."
    cd "$PROJECT_ROOT"
    if [ -n "$INSTALL_EXTRAS" ]; then
        log_info "Installing with extras: [$INSTALL_EXTRAS]"
        pip install -e ".[$INSTALL_EXTRAS]"
    else
        log_info "Installing core dependencies only (fastest)"
        pip install -e .
    fi

    # Step 4: Install SO101 robot dependencies
    log_step "Installing SO101 robot dependencies..."
    cd "$PROJECT_ROOT/operating_platform/robot/robots/so101_v1"
    pip install -e .

    # Step 5: Install SO101 arm component dependencies
    log_step "Installing SO101 arm component dependencies..."
    cd "$PROJECT_ROOT/operating_platform/robot/components/arm_normal_so101_v1"
    pip install -e .

    # Step 6: Install OpenCV (ensure we have the GUI version)
    log_step "Ensuring OpenCV with GUI support..."
    pip install opencv-python

    # Note: Rerun SDK is optional - only needed for visualization
    # Install manually if needed: pip install rerun-sdk

    # Step 7: Install system dependencies (Linux only)
    if [ "$(uname)" == "Linux" ]; then
        log_step "Installing Linux system dependencies..."

        # Detect package manager
        if command -v apt &> /dev/null; then
            # Debian/Ubuntu
            PKG_MANAGER="apt"
            log_info "Detected Debian/Ubuntu (apt)"
            log_info "Installing speech-dispatcher for voice prompts..."
            sudo apt install -y speech-dispatcher || {
                log_warn "Could not install speech-dispatcher automatically."
                log_warn "Please run: sudo apt install speech-dispatcher"
            }
            log_info "Installing portaudio for audio recording..."
            sudo apt install -y portaudio19-dev || {
                log_warn "Could not install portaudio19-dev automatically."
                log_warn "Please run: sudo apt install portaudio19-dev"
            }
        elif command -v dnf &> /dev/null; then
            # OpenEuler/Fedora/RHEL 8+
            PKG_MANAGER="dnf"
            log_info "Detected OpenEuler/Fedora/RHEL (dnf)"
            # Use --disablerepo=*-update* to prevent pulling from update repos
            # Use --setopt=install_weak_deps=False to speed up install
            DNF_OPTS="--disablerepo=*update* --setopt=install_weak_deps=False"
            log_info "Installing speech-dispatcher for voice prompts..."
            sudo dnf install -y $DNF_OPTS speech-dispatcher || {
                # Fallback without disabling repos if package not found
                sudo dnf install -y speech-dispatcher || {
                    log_warn "Could not install speech-dispatcher automatically."
                    log_warn "Please run: sudo dnf install speech-dispatcher"
                }
            }
            log_info "Installing portaudio for audio recording..."
            sudo dnf install -y $DNF_OPTS portaudio-devel || {
                sudo dnf install -y portaudio-devel || {
                    log_warn "Could not install portaudio-devel automatically."
                    log_warn "Please run: sudo dnf install portaudio-devel"
                }
            }
            log_info "Installing additional development tools..."
            sudo dnf install -y $DNF_OPTS gcc gcc-c++ make || {
                sudo dnf install -y gcc gcc-c++ make || {
                    log_warn "Could not install development tools automatically."
                    log_warn "Please run: sudo dnf install gcc gcc-c++ make"
                }
            }
        elif command -v yum &> /dev/null; then
            # CentOS/RHEL 7/older OpenEuler
            PKG_MANAGER="yum"
            log_info "Detected CentOS/RHEL/OpenEuler (yum)"
            # Use --disablerepo=*-update* to prevent pulling from update repos
            YUM_OPTS="--disablerepo=*update*"
            log_info "Installing speech-dispatcher for voice prompts..."
            sudo yum install -y $YUM_OPTS speech-dispatcher || {
                sudo yum install -y speech-dispatcher || {
                    log_warn "Could not install speech-dispatcher automatically."
                    log_warn "Please run: sudo yum install speech-dispatcher"
                }
            }
            log_info "Installing portaudio for audio recording..."
            sudo yum install -y $YUM_OPTS portaudio-devel || {
                sudo yum install -y portaudio-devel || {
                    log_warn "Could not install portaudio-devel automatically."
                    log_warn "Please run: sudo yum install portaudio-devel"
                }
            }
            log_info "Installing additional development tools..."
            sudo yum install -y $YUM_OPTS gcc gcc-c++ make || {
                sudo yum install -y gcc gcc-c++ make || {
                    log_warn "Could not install development tools automatically."
                    log_warn "Please run: sudo yum install gcc gcc-c++ make"
                }
            }
        else
            log_warn "Unknown package manager. Please install manually:"
            log_warn "  - speech-dispatcher (for voice prompts)"
            log_warn "  - portaudio development library (for audio recording)"
        fi
    fi

    # Step 9: Verify installation
    log_step "Verifying installation..."

    echo ""
    echo "Checking key packages:"

    # Check Python version
    INSTALLED_PYTHON=$(python --version 2>&1)
    echo "  Python: $INSTALLED_PYTHON"

    # Check PyTorch
    if python -c "import torch; print(f'  PyTorch: {torch.__version__}')" 2>/dev/null; then
        case $DEVICE_TYPE in
            cuda*)
                python -c "import torch; print(f'  CUDA available: {torch.cuda.is_available()}')"
                ;;
            npu)
                if python -c "import torch_npu; print(f'  torch-npu: {torch_npu.__version__}')" 2>/dev/null; then
                    python -c "import torch; import torch_npu; print(f'  NPU available: {torch.npu.is_available()}')" 2>/dev/null || true
                else
                    log_warn "torch-npu import failed"
                fi
                ;;
        esac
    else
        log_warn "PyTorch import failed"
    fi

    # Check DORA
    if command -v dora &> /dev/null; then
        DORA_VERSION=$(dora --version 2>&1 || echo "unknown")
        echo "  DORA: $DORA_VERSION"
    else
        log_warn "DORA command not found"
    fi

    # Check OpenCV
    if python -c "import cv2; print(f'  OpenCV: {cv2.__version__}')" 2>/dev/null; then
        :
    else
        log_warn "OpenCV import failed"
    fi

    # Check ZeroMQ
    if python -c "import zmq; print(f'  ZeroMQ: {zmq.__version__}')" 2>/dev/null; then
        :
    else
        log_warn "ZeroMQ import failed"
    fi

    echo ""
    echo "=========================================="
    echo "  Setup Complete!"
    echo "=========================================="
    echo ""
    log_info "Environment '$CONDA_DEFAULT_ENV' is ready to use."
    echo ""
    echo "To start data collection:"
    echo "  bash scripts/run_so101.sh"
    echo ""
    echo "Or with custom settings:"
    echo "  REPO_ID=my-dataset bash scripts/run_so101.sh"
    echo ""

    if [ "$DEVICE_TYPE" == "npu" ]; then
        echo "NPU Notes:"
        echo "  - Ensure CANN environment is sourced before running:"
        echo "    source /usr/local/Ascend/ascend-toolkit/set_env.sh"
        echo "  - For training, use --policy.device=npu"
        echo ""
    fi
}

# Run main
main "$@"
