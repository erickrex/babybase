import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { BedrockAccessStack } from '../lib/bedrock-access-stack';

describe('BedrockAccessStack', () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new BedrockAccessStack(app, 'TestStack');
    template = Template.fromStack(stack);
  });

  test('creates IAM policy with bedrock:InvokeModel action', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: [
          {
            Action: 'bedrock:InvokeModel',
            Effect: 'Allow',
            Resource: 'arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0',
          },
        ],
      },
    });
  });

  test('IAM policy resource is scoped to titan-embed-text-v2 model', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: [
          {
            Resource: 'arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0',
          },
        ],
      },
    });
  });

  test('stack output BedrockRoleArn exists', () => {
    template.hasOutput('BedrockRoleArn', {});
  });

  test('no wildcard actions in IAM policy', () => {
    const policies = template.findResources('AWS::IAM::Policy');
    for (const [, policy] of Object.entries(policies)) {
      const statements = (policy as any).Properties.PolicyDocument.Statement;
      for (const statement of statements) {
        expect(statement.Action).not.toBe('*');
        if (Array.isArray(statement.Action)) {
          expect(statement.Action).not.toContain('*');
        }
      }
    }
  });

  test('cdk synth produces valid CloudFormation template', () => {
    const json = template.toJSON();
    expect(json).toBeDefined();
    expect(json.Resources).toBeDefined();
    expect(json.Outputs).toBeDefined();
  });
});
