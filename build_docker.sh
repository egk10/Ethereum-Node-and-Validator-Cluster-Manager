#!/bin/bash
# Ethereum Node and Validator Cluster Manager - Docker Build Script

set -e

VERSION=${1:-"1.0.0"}
REGISTRY=${2:-"ghcr.io/egk10"}
IMAGE_BASE="ethereum-validator-manager"

echo "🐳 Building Docker images for version $VERSION"

# Build different release types
declare -A RELEASE_TYPES=(
    ["core"]="Essential validator management functionality"
    ["standard"]="Core + backup management + enhanced performance"  
    ["monitoring"]="Standard + Grafana/Prometheus integration"
    ["full"]="All features including experimental AI analysis"
)

for release_type in "${!RELEASE_TYPES[@]}"; do
    image_name="$REGISTRY/$IMAGE_BASE:$VERSION-$release_type"
    latest_tag="$REGISTRY/$IMAGE_BASE:latest-$release_type"
    
    echo "🔨 Building $release_type release..."
    echo "   Description: ${RELEASE_TYPES[$release_type]}"
    
    docker build \
        --target $release_type \
        --tag $image_name \
        --tag $latest_tag \
        --label "org.opencontainers.image.version=$VERSION" \
        --label "org.opencontainers.image.release-type=$release_type" \
        --label "org.opencontainers.image.description=${RELEASE_TYPES[$release_type]}" \
        --label "org.opencontainers.image.source=https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager" \
        .
    
    echo "✅ Built $image_name"
done

# Build default image (core)
default_image="$REGISTRY/$IMAGE_BASE:$VERSION"
latest_image="$REGISTRY/$IMAGE_BASE:latest"

echo "🔨 Building default image (core)..."
docker tag "$REGISTRY/$IMAGE_BASE:$VERSION-core" $default_image
docker tag "$REGISTRY/$IMAGE_BASE:$VERSION-core" $latest_image

echo "📋 Built images:"
docker images | grep $IMAGE_BASE | head -10

echo ""
echo "🚀 Usage examples:"
echo "   # Core functionality"
echo "   docker run --rm $REGISTRY/$IMAGE_BASE:$VERSION --help"
echo ""
echo "   # Check cluster versions"  
echo "   docker run --rm -v \$(pwd)/config.yaml:/app/eth_validators/config.yaml $REGISTRY/$IMAGE_BASE:$VERSION node versions-all"
echo ""
echo "   # Monitoring release with Grafana integration"
echo "   docker run --rm $REGISTRY/$IMAGE_BASE:$VERSION-monitoring --help"
echo ""
echo "🐳 To push to registry:"
echo "   docker push $REGISTRY/$IMAGE_BASE:$VERSION"
echo "   docker push $REGISTRY/$IMAGE_BASE:latest"
