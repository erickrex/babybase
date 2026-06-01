import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { PhoneticAudioStack } from '../lib/phonetic-audio-stack';

const NOVA_MODEL_ARN = 'arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0';

describe('PhoneticAudioStack', () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new PhoneticAudioStack(app, 'TestStack');
    template = Template.fromStack(stack);
  });

  test('creates a private S3 bucket with public access fully blocked', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });

  test('allows bedrock:InvokeModel scoped to the Nova model ARN', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'bedrock:InvokeModel',
            Effect: 'Allow',
            Resource: NOVA_MODEL_ARN,
          }),
        ]),
      },
    });
  });

  test('allows polly:SynthesizeSpeech', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'polly:SynthesizeSpeech',
            Effect: 'Allow',
            Resource: '*',
          }),
        ]),
      },
    });
  });

  test('S3 object actions are scoped to PutObject and GetObject', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: ['s3:PutObject', 's3:GetObject'],
            Effect: 'Allow',
          }),
        ]),
      },
    });
  });

  test('S3 access is scoped to the pronunciations/* prefix, not a wildcard', () => {
    const json = JSON.stringify(template.toJSON());
    // The S3 resource ARN is built via Fn::Join with a "/pronunciations/*" suffix.
    expect(json).toContain('/pronunciations/*');
    // No statement should grant the full s3:* wildcard action.
    expect(json).not.toContain('s3:*');
  });

  test('no wildcard "*" or "s3:*" actions in any IAM policy', () => {
    const policies = template.findResources('AWS::IAM::Policy');
    for (const [, policy] of Object.entries(policies)) {
      const statements = (policy as any).Properties.PolicyDocument.Statement;
      for (const statement of statements) {
        expect(statement.Action).not.toBe('*');
        expect(statement.Action).not.toBe('s3:*');
        if (Array.isArray(statement.Action)) {
          expect(statement.Action).not.toContain('*');
          expect(statement.Action).not.toContain('s3:*');
        }
      }
    }
  });

  test('cdk synth produces a valid CloudFormation template with outputs', () => {
    const json = template.toJSON();
    expect(json).toBeDefined();
    expect(json.Resources).toBeDefined();
    expect(json.Outputs).toBeDefined();
    template.hasOutput('PronunciationAudioBucketName', {});
    template.hasOutput('PronunciationAudioRoleArn', {});
  });
});
