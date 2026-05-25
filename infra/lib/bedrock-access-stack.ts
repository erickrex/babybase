import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface BedrockAccessStackProps extends cdk.StackProps {
  // No additional props needed — region comes from the stack environment
}

export class BedrockAccessStack extends cdk.Stack {
  public readonly bedrockRoleArn: cdk.CfnOutput;

  constructor(scope: Construct, id: string, props?: BedrockAccessStackProps) {
    super(scope, id, props);

    // IAM Role for the application to assume when invoking Bedrock
    const bedrockRole = new iam.Role(this, 'BedrockInvokeRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description: 'Role for BabyBase application to invoke Bedrock Titan Embed V2 model',
    });

    // Least-privilege policy: only bedrock:InvokeModel on the specific model
    bedrockRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['bedrock:InvokeModel'],
      resources: [
        'arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0',
      ],
    }));

    // Output the role ARN for application configuration
    this.bedrockRoleArn = new cdk.CfnOutput(this, 'BedrockRoleArn', {
      value: bedrockRole.roleArn,
      description: 'ARN of the IAM role for Bedrock Titan Embed V2 access',
      exportName: 'BabyBaseBedrockRoleArn',
    });
  }
}
