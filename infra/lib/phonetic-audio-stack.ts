import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface PhoneticAudioStackProps extends cdk.StackProps {
  // No additional props needed — region comes from the stack environment
}

export class PhoneticAudioStack extends cdk.Stack {
  public readonly audioBucketName: cdk.CfnOutput;
  public readonly phoneticAudioRoleArn: cdk.CfnOutput;

  constructor(scope: Construct, id: string, props?: PhoneticAudioStackProps) {
    super(scope, id, props);

    // Private S3 bucket for storing Polly-generated pronunciation audio.
    // Audio is regenerable but not throwaway, so retain on stack deletion.
    const bucket = new s3.Bucket(this, 'PronunciationAudioBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // IAM role for the application to assume when invoking Nova, Polly, and S3,
    // mirroring the BedrockInvokeRole pattern from BedrockAccessStack.
    const role = new iam.Role(this, 'PronunciationAudioRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description:
        'Role for BabyBase application to invoke Bedrock Nova, Amazon Polly, and access the pronunciation audio bucket',
    });

    // Least-privilege: only bedrock:InvokeModel on the pinned Nova model.
    role.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['bedrock:InvokeModel'],
      resources: [
        'arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0',
      ],
    }));

    // Least-privilege: Polly has no resource-level ARN for SynthesizeSpeech,
    // so resource '*' with the single action is the least-privilege form.
    role.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['polly:SynthesizeSpeech'],
      resources: ['*'],
    }));

    // Least-privilege: read/write only objects under the pronunciations/ prefix.
    role.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['s3:PutObject', 's3:GetObject'],
      resources: [bucket.arnForObjects('pronunciations/*')],
    }));

    // Output the bucket name for application configuration.
    this.audioBucketName = new cdk.CfnOutput(this, 'PronunciationAudioBucketName', {
      value: bucket.bucketName,
      description: 'Name of the S3 bucket storing pronunciation audio',
      exportName: 'BabyBasePronunciationAudioBucketName',
    });

    // Output the role ARN for application configuration.
    this.phoneticAudioRoleArn = new cdk.CfnOutput(this, 'PronunciationAudioRoleArn', {
      value: role.roleArn,
      description: 'ARN of the IAM role for Nova, Polly, and pronunciation audio S3 access',
      exportName: 'BabyBasePronunciationAudioRoleArn',
    });
  }
}
