package main

import (
	"os"

	"github.com/aws/aws-sdk-go-v2/service/sqs"
)

func main() {
	payments := os.Getenv("PAYMENTS_SERVICE_URL")
	_ = payments
	_ = sqs.SendMessageInput{}
}
