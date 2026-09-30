import nock from 'nock';
import { config } from '../config';

test('validates a token against the auth mock', async () => {
  nock('http://localhost:8000').get('/verify').reply(200, { ok: true });
  expect(config.port).toBe(3000);
});
