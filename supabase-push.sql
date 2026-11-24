-- Включите pg_cron и pg_net. В Vault создайте booking_url и booking_cron_secret.
-- booking_url содержит адрес сайта с https без пути и завершающей косой черты.
-- booking_cron_secret совпадает с CRON_SECRET веб-сервиса.
select cron.schedule(
  'booking-web-push',
  '* * * * *',
  $job$
    select net.http_post(
      url := site.decrypted_secret || '/jobs/push',
      headers := jsonb_build_object(
        'Authorization', 'Bearer ' || token.decrypted_secret,
        'Content-Type', 'application/json'
      ),
      timeout_milliseconds := 90000
    )
    from vault.decrypted_secrets site
    cross join vault.decrypted_secrets token
    where site.name = 'booking_url'
      and token.name = 'booking_cron_secret'
      and exists (
        select from booking.deliveries
        where accepted is null and due <= now()
      );
  $job$
);
