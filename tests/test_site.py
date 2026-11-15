from tests.fakes import stubbed_s3
from usj_ticket_prices.site import S3Site


def test_the_data_file_is_written_as_json_that_caches_only_briefly():
    s3, stubber = stubbed_s3()
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": "site-bucket",
            "Key": "data.json",
            "Body": b'{"guest_type":"Adult"}',
            "ContentType": "application/json",
            "CacheControl": "max-age=300",
        },
    )

    S3Site(s3, "site-bucket").write_data_file(b'{"guest_type":"Adult"}')

    stubber.assert_no_pending_responses()
