MODULE := github.com/48Nauts-Operator/antbot-exec
BINARY := bin/antbot-exec
PROTO_DIR := api/proto
GEN_GO := api/gen
GEN_PY := ../antbot/exec_bridge/gen

.PHONY: proto build test install clean

proto:
	@echo "==> Generating Go stubs..."
	@mkdir -p $(GEN_GO)
	protoc \
		--proto_path=$(PROTO_DIR) \
		--go_out=$(GEN_GO) --go_opt=paths=source_relative \
		--go-grpc_out=$(GEN_GO) --go-grpc_opt=paths=source_relative \
		$(PROTO_DIR)/antbot.proto
	@echo "==> Generating Python stubs..."
	@mkdir -p $(GEN_PY)
	python3 -m grpc_tools.protoc \
		--proto_path=$(PROTO_DIR) \
		--python_out=$(GEN_PY) \
		--pyi_out=$(GEN_PY) \
		--grpc_python_out=$(GEN_PY) \
		$(PROTO_DIR)/antbot.proto
	@touch $(GEN_PY)/__init__.py
	@# Fix grpc-tools absolute imports to package-relative imports
	@sed -i '' 's/^import antbot_pb2/from antbot.exec_bridge.gen import antbot_pb2/' $(GEN_PY)/antbot_pb2_grpc.py
	@echo "Done."

build: proto
	@mkdir -p bin
	go build -o $(BINARY) ./cmd/antbot-exec

test:
	go test ./...

install: build
	@mkdir -p ~/.antbot/bin
	cp $(BINARY) ~/.antbot/bin/antbot-exec
	@echo "Installed to ~/.antbot/bin/antbot-exec"

clean:
	rm -rf bin $(GEN_GO)/*.go $(GEN_PY)/*.py $(GEN_PY)/*.pyi
