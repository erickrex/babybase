#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { BedrockAccessStack } from '../lib/bedrock-access-stack';

const app = new cdk.App();

new BedrockAccessStack(app, 'BabyBaseBedrockAccessStack', {
  env: {
    region: app.node.tryGetContext('region') || 'us-east-1',
  },
  description: 'IAM role for BabyBase to invoke Bedrock Titan Embed V2 model',
});
