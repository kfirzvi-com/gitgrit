module github.com/kfirzvi-com/gitgrit-demo-messy-monorepo/services/orders-service

go 1.22

require (
	demo/shared-lib v0.0.0
	github.com/aws/aws-sdk-go-v2/service/sqs v1.34.0
)

replace demo/shared-lib => ../../packages/shared-lib
