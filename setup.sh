#!/bin/bash
# Setup script for Asphalt MD project
#
# Usage:
#   ./setup.sh              # Full setup (asphalt_venv + all dependencies)
#   ./setup.sh --minimal    # Minimal setup (core dependencies only)
#   ./setup.sh --frontend   # Setup frontend only
#   ./setup.sh --lammps     # Install LAMMPS
#   ./setup.sh --packmol    # Install Packmol
#   ./setup.sh --all-tools  # Install LAMMPS + Packmol + Python deps
#   ./setup.sh --llm        # Setup LLM agent dependencies

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$PROJECT_ROOT/tools"

cd "$PROJECT_ROOT"

echo "=== Asphalt MD Project Setup ==="
echo ""

# Parse arguments
SETUP_TYPE="${1:-full}"

setup_venv() {
    if [ ! -d "asphalt_venv" ]; then
        echo "Creating virtual environment (asphalt_venv)..."
        python3 -m venv asphalt_venv
    else
        echo "Virtual environment (asphalt_venv) already exists."
    fi
    source asphalt_venv/bin/activate
    echo "Virtual environment activated."
}

install_python_deps() {
    echo "Installing Python dependencies..."
    pip install --upgrade pip

    case "$1" in
        "minimal")
            pip install -e .
            ;;
        "full")
            pip install -e ".[all]"
            # Install ML and GraphQL packages explicitly for Phase 4
            echo "Installing ML and GraphQL dependencies..."
            pip install "numpy<2" scikit-learn xgboost lightgbm strawberry-graphql alembic
            # Install LLM agent packages
            echo "Installing LLM agent dependencies..."
            pip install anthropic openai httpx aiohttp tiktoken
            ;;
        "llm")
            pip install -e ".[llm]"
            pip install anthropic openai httpx aiohttp tiktoken
            ;;
        "api")
            pip install -e ".[api,db]"
            pip install strawberry-graphql
            ;;
        "queue")
            pip install -e ".[queue]"
            ;;
        "ml")
            pip install -e ".[ml]"
            pip install "numpy<2" scikit-learn xgboost lightgbm
            ;;
    esac
}

install_frontend_deps() {
    # Frontend dependencies are managed by start_all.sh (Single Source of Truth)
    echo ""
    echo "=== Frontend Dependencies ==="
    echo "Frontend dependencies are managed by start_all.sh"
    echo ""
    echo "To install/verify frontend dependencies, run:"
    echo "  ./start_all.sh --check"
    echo ""
}

install_lammps() {
    echo "=== Installing LAMMPS ==="

    mkdir -p "$TOOLS_DIR"
    cd "$TOOLS_DIR"

    LAMMPS_VERSION="stable_2Aug2023_update3"
    LAMMPS_DIR="$TOOLS_DIR/lammps"

    if [ -f "$LAMMPS_DIR/build/lmp" ]; then
        echo "LAMMPS already installed at $LAMMPS_DIR/build/lmp"
        return 0
    fi

    # Install dependencies
    echo "Installing LAMMPS build dependencies..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y build-essential cmake libfftw3-dev libopenmpi-dev
    elif command -v yum &> /dev/null; then
        sudo yum install -y gcc gcc-c++ cmake fftw-devel openmpi-devel
    elif command -v brew &> /dev/null; then
        brew install cmake fftw open-mpi
    fi

    # Download LAMMPS
    if [ ! -d "$LAMMPS_DIR" ]; then
        echo "Downloading LAMMPS $LAMMPS_VERSION..."
        git clone --depth 1 --branch $LAMMPS_VERSION https://github.com/lammps/lammps.git "$LAMMPS_DIR"
    fi

    # Build LAMMPS
    cd "$LAMMPS_DIR"
    mkdir -p build
    cd build

    echo "Building LAMMPS (this may take several minutes)..."
    cmake ../cmake \
        -DCMAKE_BUILD_TYPE=Release \
        -DPKG_MOLECULE=yes \
        -DPKG_RIGID=yes \
        -DPKG_KSPACE=yes \
        -DPKG_MANYBODY=yes \
        -DPKG_EXTRA-MOLECULE=yes \
        -DPKG_EXTRA-PAIR=yes \
        -DBUILD_MPI=yes

    make -j$(nproc)

    echo "LAMMPS installed at $LAMMPS_DIR/build/lmp"

    # Create symlink
    mkdir -p "$PROJECT_ROOT/bin"
    ln -sf "$LAMMPS_DIR/build/lmp" "$PROJECT_ROOT/bin/lmp"

    cd "$PROJECT_ROOT"
}

install_packmol() {
    echo "=== Installing Packmol ==="

    mkdir -p "$TOOLS_DIR"
    cd "$TOOLS_DIR"

    PACKMOL_DIR="$TOOLS_DIR/packmol"

    if [ -f "$PACKMOL_DIR/packmol" ]; then
        echo "Packmol already installed at $PACKMOL_DIR/packmol"
        return 0
    fi

    # Install gfortran if needed
    echo "Installing Packmol build dependencies..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y gfortran
    elif command -v yum &> /dev/null; then
        sudo yum install -y gcc-gfortran
    elif command -v brew &> /dev/null; then
        brew install gcc
    fi

    # Download Packmol
    if [ ! -d "$PACKMOL_DIR" ]; then
        echo "Downloading Packmol..."
        git clone https://github.com/m3g/packmol.git "$PACKMOL_DIR"
    fi

    # Build Packmol
    cd "$PACKMOL_DIR"
    echo "Building Packmol..."
    make

    echo "Packmol installed at $PACKMOL_DIR/packmol"

    # Create symlink
    mkdir -p "$PROJECT_ROOT/bin"
    ln -sf "$PACKMOL_DIR/packmol" "$PROJECT_ROOT/bin/packmol"

    cd "$PROJECT_ROOT"
}

create_molecule_library() {
    echo "=== Creating Molecule Library ==="

    DATA_DIR="$PROJECT_ROOT/data/molecules"
    mkdir -p "$DATA_DIR"

    if [ -f "$DATA_DIR/molecule_library.yaml" ]; then
        echo "Molecule library already exists."
        return 0
    fi

    # Create molecule library YAML
    cat > "$DATA_DIR/molecule_library.yaml" << 'EOF'
# Molecule Library for Asphalt Binder Simulations
# SARA Components: Saturates, Aromatics, Resins, Asphaltenes

molecules:
  hexadecane:
    file: "hexadecane.pdb"
    sara_type: saturate
    molecular_weight: 226.44
    num_atoms: 50
    formula: "C16H34"
    description: "Linear saturate representative"

  naphthalene:
    file: "naphthalene.pdb"
    sara_type: aromatic
    molecular_weight: 128.17
    num_atoms: 18
    formula: "C10H8"
    description: "Simple aromatic representative"

  benzothiophene:
    file: "benzothiophene.pdb"
    sara_type: resin
    molecular_weight: 134.20
    num_atoms: 17
    formula: "C8H6S"
    description: "Resin representative with sulfur"

  coronene:
    file: "coronene.pdb"
    sara_type: asphaltene
    molecular_weight: 300.35
    num_atoms: 36
    formula: "C24H12"
    description: "Polycyclic aromatic asphaltene model"

defaults:
  saturate: hexadecane
  aromatic: naphthalene
  resin: benzothiophene
  asphaltene: coronene
EOF

    # Create sample PDB files
    echo "Creating sample molecule PDB files..."

    # Hexadecane (C16H34) - simplified structure
    cat > "$DATA_DIR/hexadecane.pdb" << 'EOF'
HEADER    HEXADECANE
COMPND    C16H34
ATOM      1  C1  HEX     1       0.000   0.000   0.000  1.00  0.00           C
ATOM      2  C2  HEX     1       1.540   0.000   0.000  1.00  0.00           C
ATOM      3  C3  HEX     1       2.310   1.260   0.000  1.00  0.00           C
ATOM      4  C4  HEX     1       3.850   1.260   0.000  1.00  0.00           C
ATOM      5  C5  HEX     1       4.620   2.520   0.000  1.00  0.00           C
ATOM      6  C6  HEX     1       6.160   2.520   0.000  1.00  0.00           C
ATOM      7  C7  HEX     1       6.930   3.780   0.000  1.00  0.00           C
ATOM      8  C8  HEX     1       8.470   3.780   0.000  1.00  0.00           C
ATOM      9  C9  HEX     1       9.240   5.040   0.000  1.00  0.00           C
ATOM     10  C10 HEX     1      10.780   5.040   0.000  1.00  0.00           C
ATOM     11  C11 HEX     1      11.550   6.300   0.000  1.00  0.00           C
ATOM     12  C12 HEX     1      13.090   6.300   0.000  1.00  0.00           C
ATOM     13  C13 HEX     1      13.860   7.560   0.000  1.00  0.00           C
ATOM     14  C14 HEX     1      15.400   7.560   0.000  1.00  0.00           C
ATOM     15  C15 HEX     1      16.170   8.820   0.000  1.00  0.00           C
ATOM     16  C16 HEX     1      17.710   8.820   0.000  1.00  0.00           C
END
EOF

    # Naphthalene (C10H8)
    cat > "$DATA_DIR/naphthalene.pdb" << 'EOF'
HEADER    NAPHTHALENE
COMPND    C10H8
ATOM      1  C1  NAP     1       0.000   0.000   0.000  1.00  0.00           C
ATOM      2  C2  NAP     1       1.200   0.700   0.000  1.00  0.00           C
ATOM      3  C3  NAP     1       2.400   0.000   0.000  1.00  0.00           C
ATOM      4  C4  NAP     1       2.400  -1.400   0.000  1.00  0.00           C
ATOM      5  C5  NAP     1       1.200  -2.100   0.000  1.00  0.00           C
ATOM      6  C6  NAP     1       0.000  -1.400   0.000  1.00  0.00           C
ATOM      7  C7  NAP     1       3.600   0.700   0.000  1.00  0.00           C
ATOM      8  C8  NAP     1       4.800   0.000   0.000  1.00  0.00           C
ATOM      9  C9  NAP     1       4.800  -1.400   0.000  1.00  0.00           C
ATOM     10  C10 NAP     1       3.600  -2.100   0.000  1.00  0.00           C
END
EOF

    # Benzothiophene (C8H6S)
    cat > "$DATA_DIR/benzothiophene.pdb" << 'EOF'
HEADER    BENZOTHIOPHENE
COMPND    C8H6S
ATOM      1  C1  BTH     1       0.000   0.000   0.000  1.00  0.00           C
ATOM      2  C2  BTH     1       1.200   0.700   0.000  1.00  0.00           C
ATOM      3  C3  BTH     1       2.400   0.000   0.000  1.00  0.00           C
ATOM      4  C4  BTH     1       2.400  -1.400   0.000  1.00  0.00           C
ATOM      5  C5  BTH     1       1.200  -2.100   0.000  1.00  0.00           C
ATOM      6  C6  BTH     1       0.000  -1.400   0.000  1.00  0.00           C
ATOM      7  S1  BTH     1       3.600   0.700   0.000  1.00  0.00           S
ATOM      8  C7  BTH     1       4.200  -0.900   0.000  1.00  0.00           C
ATOM      9  C8  BTH     1       3.300  -1.800   0.000  1.00  0.00           C
END
EOF

    # Coronene (C24H12)
    cat > "$DATA_DIR/coronene.pdb" << 'EOF'
HEADER    CORONENE
COMPND    C24H12
ATOM      1  C1  COR     1       0.000   0.000   0.000  1.00  0.00           C
ATOM      2  C2  COR     1       1.200   0.700   0.000  1.00  0.00           C
ATOM      3  C3  COR     1       2.400   0.000   0.000  1.00  0.00           C
ATOM      4  C4  COR     1       2.400  -1.400   0.000  1.00  0.00           C
ATOM      5  C5  COR     1       1.200  -2.100   0.000  1.00  0.00           C
ATOM      6  C6  COR     1       0.000  -1.400   0.000  1.00  0.00           C
ATOM      7  C7  COR     1       3.600   0.700   0.000  1.00  0.00           C
ATOM      8  C8  COR     1       4.800   0.000   0.000  1.00  0.00           C
ATOM      9  C9  COR     1       4.800  -1.400   0.000  1.00  0.00           C
ATOM     10  C10 COR     1       3.600  -2.100   0.000  1.00  0.00           C
ATOM     11  C11 COR     1       6.000   0.700   0.000  1.00  0.00           C
ATOM     12  C12 COR     1       7.200   0.000   0.000  1.00  0.00           C
ATOM     13  C13 COR     1       7.200  -1.400   0.000  1.00  0.00           C
ATOM     14  C14 COR     1       6.000  -2.100   0.000  1.00  0.00           C
ATOM     15  C15 COR     1       1.200   2.100   0.000  1.00  0.00           C
ATOM     16  C16 COR     1       2.400   2.800   0.000  1.00  0.00           C
ATOM     17  C17 COR     1       3.600   2.100   0.000  1.00  0.00           C
ATOM     18  C18 COR     1       4.800   2.800   0.000  1.00  0.00           C
ATOM     19  C19 COR     1       6.000   2.100   0.000  1.00  0.00           C
ATOM     20  C20 COR     1       1.200  -3.500   0.000  1.00  0.00           C
ATOM     21  C21 COR     1       2.400  -4.200   0.000  1.00  0.00           C
ATOM     22  C22 COR     1       3.600  -3.500   0.000  1.00  0.00           C
ATOM     23  C23 COR     1       4.800  -4.200   0.000  1.00  0.00           C
ATOM     24  C24 COR     1       6.000  -3.500   0.000  1.00  0.00           C
END
EOF

    echo "Molecule library created at $DATA_DIR"
}

update_test_paths() {
    echo "=== Updating Test Paths ==="

    # Update test file paths to use project-local tools
    LAMMPS_PATH="$PROJECT_ROOT/bin/lmp"
    PACKMOL_PATH="$PROJECT_ROOT/bin/packmol"
    MOLECULE_LIB="$PROJECT_ROOT/data/molecules"

    TEST_FILE="$PROJECT_ROOT/tests/e2e/test_asphalt_simulation.py"

    if [ -f "$TEST_FILE" ]; then
        sed -i "s|LAMMPS_EXE = .*|LAMMPS_EXE = \"$LAMMPS_PATH\"|" "$TEST_FILE"
        sed -i "s|PACKMOL_EXE = .*|PACKMOL_EXE = \"$PACKMOL_PATH\"|" "$TEST_FILE"
        sed -i "s|MOLECULE_LIB = .*|MOLECULE_LIB = Path(\"$MOLECULE_LIB\")|" "$TEST_FILE"
        echo "Updated test paths in $TEST_FILE"
    fi
}

case "$SETUP_TYPE" in
    "--minimal")
        setup_venv
        install_python_deps "minimal"
        echo ""
        echo "Minimal setup complete!"
        ;;
    "--frontend")
        echo ""
        echo "=== Frontend Setup ==="
        echo "Frontend dependencies are now managed by start_all.sh"
        echo ""
        echo "Run the following command to install frontend dependencies:"
        echo "  ./start_all.sh --check"
        echo ""
        ;;
    "--api")
        setup_venv
        install_python_deps "api"
        echo ""
        echo "API setup complete!"
        ;;
    "--queue")
        setup_venv
        install_python_deps "queue"
        echo ""
        echo "Queue setup complete!"
        ;;
    "--ml")
        setup_venv
        install_python_deps "ml"
        echo ""
        echo "ML setup complete!"
        echo "Installed: scikit-learn, xgboost, lightgbm"
        ;;
    "--llm")
        setup_venv
        install_python_deps "llm"
        echo ""
        echo "LLM agent setup complete!"
        echo "Installed: anthropic, openai, httpx, aiohttp, tiktoken"
        ;;
    "--lammps")
        install_lammps
        echo ""
        echo "LAMMPS installation complete!"
        echo "Binary location: $PROJECT_ROOT/bin/lmp"
        ;;
    "--packmol")
        install_packmol
        echo ""
        echo "Packmol installation complete!"
        echo "Binary location: $PROJECT_ROOT/bin/packmol"
        ;;
    "--molecules")
        create_molecule_library
        echo ""
        echo "Molecule library setup complete!"
        ;;
    "--all-tools")
        setup_venv
        install_python_deps "full"
        install_lammps
        install_packmol
        create_molecule_library
        update_test_paths
        echo ""
        echo "=== All Tools Setup Complete ==="
        echo ""
        echo "LAMMPS:   $PROJECT_ROOT/bin/lmp"
        echo "Packmol:  $PROJECT_ROOT/bin/packmol"
        echo "Molecules: $PROJECT_ROOT/data/molecules"
        ;;
    "--update-tests")
        update_test_paths
        echo ""
        echo "Test paths updated!"
        ;;
    *)
        setup_venv
        install_python_deps "full"
        echo ""
        echo "=== Setup Complete (v00.64.00) ==="
        echo ""
        echo "To activate the virtual environment:"
        echo "  source asphalt_venv/bin/activate"
        echo ""
        echo "To start all services (includes frontend dependency check):"
        echo "  ./start_all.sh"
        echo ""
        echo "To check/install dependencies only:"
        echo "  ./start_all.sh --check"
        echo ""
        echo "To install LAMMPS and Packmol for full E2E tests:"
        echo "  ./setup.sh --all-tools"
        echo ""
        echo "=== LLM Agent System ==="
        echo ""
        echo "LLM agent dependencies are automatically included in full setup."
        echo "To install LLM dependencies only:"
        echo "  ./setup.sh --llm"
        echo ""
        ;;
esac
