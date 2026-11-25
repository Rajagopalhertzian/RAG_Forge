#!/usr/bin/env bash
# =============================================================================
# MCP mTLS Certificate Generation Script
# =============================================================================
# Generates self-signed CA + server/client certificates for development.
# For production, use cert-manager with Let's Encrypt or AWS ACM.
#
# Outputs to docker/certs/ (gitignored)
# Valid for 365 days
# =============================================================================

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CERTS_DIR="${PROJECT_ROOT}/docker/certs"
DAYS_VALID=365
KEY_SIZE=2048

# Certificate details
CA_SUBJECT="/C=US/ST=CA/L=San Francisco/O=ContextForge/OU=MCP/CN=ContextForge MCP CA"
SERVER_SUBJECT="/C=US/ST=CA/L=San Francisco/O=ContextForge/OU=MCP/CN=contextforge-mcp-gateway"
CLIENT_SUBJECT="/C=US/ST=CA/L=San Francisco/O=ContextForge/OU=MCP/CN=mcp-client"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# Check if openssl is available
if ! command -v openssl &> /dev/null; then
    log_error "openssl not found. Please install OpenSSL."
    exit 1
fi

# Create certs directory
mkdir -p "${CERTS_DIR}"

# Check if certificates already exist
if [[ -f "${CERTS_DIR}/ca.pem" && -f "${CERTS_DIR}/server.pem" && -f "${CERTS_DIR}/client.pem" ]]; then
    log_warn "Certificates already exist in ${CERTS_DIR}"
    read -p "Overwrite existing certificates? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Skipping certificate generation."
        exit 0
    fi
fi

log_info "Generating mTLS certificates for MCP Gateway..."
log_info "Output directory: ${CERTS_DIR}"
log_info "Validity: ${DAYS_VALID} days"
log_info "Key size: ${KEY_SIZE} bits"

# =============================================================================
# 1. Generate CA Private Key
# =============================================================================
log_info "Step 1/6: Generating CA private key..."
openssl genrsa -out "${CERTS_DIR}/ca-key.pem" ${KEY_SIZE}
chmod 400 "${CERTS_DIR}/ca-key.pem"
log_success "CA private key generated: ${CERTS_DIR}/ca-key.pem"

# =============================================================================
# 2. Generate CA Certificate (Self-Signed)
# =============================================================================
log_info "Step 2/6: Generating CA certificate (self-signed)..."
openssl req -x509 -new -nodes \
    -key "${CERTS_DIR}/ca-key.pem" \
    -sha256 \
    -days ${DAYS_VALID} \
    -out "${CERTS_DIR}/ca.pem" \
    -subj "${CA_SUBJECT}"
log_success "CA certificate generated: ${CERTS_DIR}/ca.pem"

# =============================================================================
# 3. Generate Server Private Key
# =============================================================================
log_info "Step 3/6: Generating server private key..."
openssl genrsa -out "${CERTS_DIR}/server-key.pem" ${KEY_SIZE}
chmod 400 "${CERTS_DIR}/server-key.pem"
log_success "Server private key generated: ${CERTS_DIR}/server-key.pem"

# =============================================================================
# 4. Generate Server CSR
# =============================================================================
log_info "Step 4/6: Generating server CSR..."
openssl req -new \
    -key "${CERTS_DIR}/server-key.pem" \
    -out "${CERTS_DIR}/server.csr" \
    -subj "${SERVER_SUBJECT}"
log_success "Server CSR generated: ${CERTS_DIR}/server.csr"

# =============================================================================
# 5. Sign Server Certificate with CA
# =============================================================================
log_info "Step 5/6: Signing server certificate with CA..."
cat > "${CERTS_DIR}/server-ext.cnf" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names
extendedKeyUsage = serverAuth, clientAuth

[alt_names]
DNS.1 = localhost
DNS.2 = contextforge-mcp-gateway
DNS.3 = contextforge-mcp-gateway.staging
DNS.4 = contextforge-mcp-gateway.prod
IP.1 = 127.0.0.1
IP.2 = ::1
EOF

openssl x509 -req \
    -in "${CERTS_DIR}/server.csr" \
    -CA "${CERTS_DIR}/ca.pem" \
    -CAkey "${CERTS_DIR}/ca-key.pem" \
    -CAcreateserial \
    -out "${CERTS_DIR}/server.pem" \
    -days ${DAYS_VALID} \
    -sha256 \
    -extfile "${CERTS_DIR}/server-ext.cnf"
log_success "Server certificate generated: ${CERTS_DIR}/server.pem"

# =============================================================================
# 6. Generate Client Private Key + Certificate
# =============================================================================
log_info "Step 6/6: Generating client certificate..."

# Client private key
openssl genrsa -out "${CERTS_DIR}/client-key.pem" ${KEY_SIZE}
chmod 400 "${CERTS_DIR}/client-key.pem"

# Client CSR
openssl req -new \
    -key "${CERTS_DIR}/client-key.pem" \
    -out "${CERTS_DIR}/client.csr" \
    -subj "${CLIENT_SUBJECT}"

# Client certificate extensions
cat > "${CERTS_DIR}/client-ext.cnf" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment
extendedKeyUsage = clientAuth
EOF

# Sign client certificate with CA
openssl x509 -req \
    -in "${CERTS_DIR}/client.csr" \
    -CA "${CERTS_DIR}/ca.pem" \
    -CAkey "${CERTS_DIR}/ca-key.pem" \
    -CAcreateserial \
    -out "${CERTS_DIR}/client.pem" \
    -days ${DAYS_VALID} \
    -sha256 \
    -extfile "${CERTS_DIR}/client-ext.cnf"
log_success "Client certificate generated: ${CERTS_DIR}/client.pem"

# =============================================================================
# Cleanup temporary files
# =============================================================================
rm -f "${CERTS_DIR}/server.csr" "${CERTS_DIR}/server-ext.cnf" \
      "${CERTS_DIR}/client.csr" "${CERTS_DIR}/client-ext.cnf" \
      "${CERTS_DIR}/ca.srl"

# =============================================================================
# Verify certificates
# =============================================================================
log_info "Verifying certificates..."

# Verify CA
openssl x509 -in "${CERTS_DIR}/ca.pem" -text -noout | grep -E "(Subject:|Issuer:|Not Before|Not After)" | head -4

# Verify server cert
openssl x509 -in "${CERTS_DIR}/server.pem" -text -noout | grep -E "(Subject:|Issuer:|Not Before|Not After|DNS:|IP Address:)" | head -8

# Verify client cert
openssl x509 -in "${CERTS_DIR}/client.pem" -text -noout | grep -E "(Subject:|Issuer:|Not Before|Not After)" | head -4

# Verify server cert against CA
if openssl verify -CAfile "${CERTS_DIR}/ca.pem" "${CERTS_DIR}/server.pem" > /dev/null 2>&1; then
    log_success "Server certificate verified against CA"
else
    log_error "Server certificate verification failed!"
    exit 1
fi

# Verify client cert against CA
if openssl verify -CAfile "${CERTS_DIR}/ca.pem" "${CERTS_DIR}/client.pem" > /dev/null 2>&1; then
    log_success "Client certificate verified against CA"
else
    log_error "Client certificate verification failed!"
    exit 1
fi

# =============================================================================
# Summary
# =============================================================================
echo
log_success "mTLS certificates generated successfully!"
echo
echo "Generated files in ${CERTS_DIR}:"
echo "  CA Certificate:        ca.pem"
echo "  CA Private Key:        ca-key.pem (keep secure!)"
echo "  Server Certificate:    server.pem"
echo "  Server Private Key:    server-key.pem (keep secure!)"
echo "  Client Certificate:    client.pem"
echo "  Client Private Key:    client-key.pem (keep secure!)"
echo
echo "To use with MCP Gateway:"
echo "  1. Set in GatewayConfig:"
echo "     mtls_enabled: true"
echo "     cert_path: /certs/server.pem"
echo "     key_path: /certs/server-key.pem"
echo "     ca_path: /certs/ca.pem"
echo "  2. Mount certs directory in Docker:"
echo "     -v \${PWD}/docker/certs:/certs:ro"
echo
log_warn "IMPORTANT: For production, use cert-manager with Let's Encrypt or AWS ACM."
log_warn "See: https://cert-manager.io/docs/ or AWS Certificate Manager documentation."