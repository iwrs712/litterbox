IMAGE := registry.runlet.cn/litterbox/orchestrator-service:latest

.PHONY: build push

build:
	docker buildx build --platform linux/amd64 --load -t $(IMAGE) -f Dockerfile .

push:
	docker push $(IMAGE)
